# Bucket E — possibly-unknown miss cases (run #18)

Four micro-benchmark snippets whose misses don't fit the known translation/analysis-precision buckets. Each lists the source, the ground-truth entries we're missing, and a short note on what might be going on.

---

## 1. `assignments/chained` — chained assignment binding

`vendor/TypeEvalPy/micro-benchmark/python_features/assignments/chained/main.py`:

```python
 1  # Two variables are assigned a function via chained assignment.
 2
 3
 4  def func1():
 5      return "Hello from func1"
 6
 7
 8  def func2():
 9      return 42
10
11
12  a = b = func1
13
14  c = b()
15
16  a = b = func2
17
18  d = a()
```

**Missing GT entries (LOCATION_MISS in run #18):**

| line | col | kind | name | expected |
|---:|---:|---|---|---|
| 12 | 1 | variable | `a` | `["callable"]` |
| 12 | 5 | variable | `b` | `["callable"]` |
| 16 | 5 | variable | `b` | `["callable"]` |

`c = b()` (line 14) and `d = a()` (line 18) are both EXACT — so `a` and `b` resolve correctly when called, but they don't surface as named bindings at the chained-assignment site. Line 16 `a` does surface (rebind path); line 12 `a` + `b` and line 16 `b` are the missing first-binds.

---

## 2. `assignments/augmented` — augmented assign rebind not surfacing

`vendor/TypeEvalPy/micro-benchmark/python_features/assignments/augmented/main.py`:

```python
 1  # A program to demonstrate the use of augmented assignments.
 2  # Augmented assignments are used to assign the result of func1
 3
 4
 5  def func1(a):
 6      a += 3
 7      a *= 2
 8      return a
 9
10
11  b = func1(5)
```

**Missing GT entries (LOCATION_MISS):**

| line | col | kind | name | function | expected |
|---:|---:|---|---|---|---|
| 6 | 5 | variable | `a` | `func1` | `["int"]` |
| 7 | 5 | variable | `a` | `func1` | `["int"]` |

The parameter `a` at line 5 col 11 (`["int"]`) is EXACT, and the return at line 8 (`["int"]`) is also EXACT. `a` reaches the return correctly — but GT also expects `a` to be queryable at each augmented-assign statement (lines 6, 7) and we don't surface it there.

---

## 3. `assignments/starred` — starred-middle name binding

`vendor/TypeEvalPy/micro-benchmark/python_features/assignments/starred/main.py`:

```python
 1  # Functions are assigned to variables via starred assignment
 2  def func1():
 3      return "Hello from func1"
 4
 5
 6  def func2():
 7      return 42
 8
 9
10  def func3():
11      return 42.5
12
13
14  def func4():
15      return [2, 4]
16
17
18  a, *b, c = func1, func2, func3, func4
19
20  d = a()
21  e = b[0]()
22  f = b[1]()
23  g = c()
```

**Missing GT entries (LOCATION_MISS):**

| line | col | kind | name | expected |
|---:|---:|---|---|---|
| 18 | 5 | variable | `b` | `["list"]` |
| 18 | 5 | variable | `b[0]` | `["callable"]` |
| 18 | 5 | variable | `b[1]` | `["callable"]` |

GT keys the starred name `b` at **col 5**. After the per-target position fix, `a` (col 1) and `c` (col 8) match correctly. `b` doesn't. Question is what column the analysis is emitting for the starred-middle name — if it's emitting the `b` identifier's own column (col 4) or the `*` token's column (col 3), neither matches GT's col 5.

Related (TYPE_MISS, not LM, but same snippet):
- `e = b[0]()` line 21 col 1 — GT `["int"]`, predicted `["float", "int"]`
- `f = b[1]()` line 22 col 1 — GT `["float"]`, predicted `["float", "int"]`

`b`'s list element is a union of the slice contents, so per-index access gets the union. Same heterogeneous-list shape as `lists/simple`.

---

## 4. `direct_calls/return_call` — qualified name on nested function

`vendor/TypeEvalPy/micro-benchmark/python_features/direct_calls/return_call/main.py`:

```python
 1  # A function `func` is called and returns a function `return_func` which is later called directly in the form func()().
 2
 3
 4  def return_func():
 5      def nested_return_func():
 6          return "Hello from nested_return_func"
 7
 8      return nested_return_func
 9
10
11  def func():
12      return return_func
13
14
15  a = func()()
16  b = func()()()
```

**Missing GT entry (LOCATION_MISS):**

| line | col | kind | name | expected |
|---:|---:|---|---|---|
| 5 | 9 | return | `return_func.nested_return_func` | `["str"]` |

GT uses a qualified name `return_func.nested_return_func` for the nested function's return. The position (line 5 col 9) is the `nested_return_func` identifier in `def nested_return_func():`. The analysis presumably surfaces this as a `FunctionView` with `name: "nested_return_func"` (unqualified). Two possible fixes:

- **Analysis side:** `FunctionView.name` for nested defs should be the dotted path (`return_func.nested_return_func`).
- **Adapter side:** when looking up a return GT by qualified name, strip the parent qualifier(s) and match against `FunctionView.name` using `source_position` to disambiguate when multiple defs share a short name.

The other GT entries in this snippet — line 4 callable, line 11 callable, line 15 callable, line 16 str — all resolve correctly.
