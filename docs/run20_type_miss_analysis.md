# Run #20 — TYPE_MISS analysis

Run #20 of Archway on TypeEvalPy micro: **398/850 EXACT** · **78 TYPE_MISS** · 374 LOCATION_MISS. This doc covers the TYPE_MISS bucket only (cases where we predicted a type but it was wrong) — LOCATION_MISS cases are tracked via the translation-error breakdown elsewhere.

The 78 cases sort into 9 root-cause buckets, ranked here by likely-actionable potential.

---

## Bucket 1 — Multi-parameter binding regression (17 cases) — **probable regression**

Pattern: a function's **first** positional parameter resolves correctly, but the **second/third/N-th** positional parameters predict `NameError`. Consistent across class methods, lambdas, multi-arg defs, multi-arg defaults, and *args splats.

`["callable"] → ["NameError"]` × 7 · `["str"] → ["NameError"]` × 4 · `["int"] → ["NameError"]` × 3 · `["float", "int"] → ["NameError"]` × 1 · `["tuple"] → ["NameError"]` × 1 · `["callable"] → ["NameError"]` × 1

### `args/multiple`

```python
def my_sum(a, b, *integers):       # a OK; b → NameError; integers → NameError
    result = a + b
    for x in integers:
        result += x
    return result

def func(a):
    return a(1, 2, 3)

b = func(my_sum)
```

### `lambdas/chained_calls`

```python
def func3(a):                       # a OK
    return a(1)

def func2(a, b):                    # a OK; b → NameError
    a(1)
    return func3(b)

def func1(a, b, c):                 # a OK; b → NameError; c → NameError
    a(1)
    return func2(b, c)

d = func1(lambda x: x + 1, lambda x: x + 2, lambda x: x + 3)
```

### `classes/parameter_call`

```python
class MyClass:
    def func3(self):
        return "Hello from func3"

    def func2(self, a):             # a → NameError (param at line 6 col 21)
        return a()

    def func1(self, a, b):          # a → NameError; b → NameError
        return a(b)

a = MyClass()
d = a.func1(a.func2, a.func3)
```

### `decorators/assigned` and `decorators/param_call` (same pattern)

```python
def wrapper(a, b):                  # a OK; b → NameError
    result = f(a, b)
    return result
```

### `functions/composition`, `functions/default`

```python
def add(x, y):                      # x OK; y → NameError
    return x + y

def my_func(x=0, y=0):              # x OK; y → NameError
    return x + y
```

### `kwargs/chained_call`

```python
def func1(a, b=func2):              # a OK; b → NameError
    return a(b)
```

**Recommendation:** Confirm whether multi-arg parameter binding handles index ≥ 1 correctly. The pattern is consistent enough that it looks like a single binding-loop bug rather than per-snippet failure modes.

---

## Bucket 2 — `zip` / `map` builtin signatures (13 cases)

`zip` and `map` aren't modeled. `map` raises `TypeError`; `zip` partially resolves but produces wrong element shapes.

### `builtins/map`

```python
def func(x):
    return x                        # GT(return func): float, int, str — predicted: [] (empty)

res = map(func, [1, "Hello", 3.0])  # GT: map        Predicted: TypeError
x, y, z = res                       # all → TypeError; GT wants int/str/float
```

### `builtins/zip`

```python
names = ["Alice", "Bob"]
ages = [30, 25]

combined = zip(names, ages)         # GT: zip        Predicted: list
result = list(combined)             # GT: list (correct, exact)

# These indexed accesses all predict "tuple" — but the test wants each
# unpacked element typed (str at [i][0], int at [i][1]):
# result[0][0]  GT: str   Predicted: tuple
# result[0][1]  GT: int   Predicted: tuple
# result[1][0]  GT: str   Predicted: tuple
# result[1][1]  GT: int   Predicted: tuple
```

`zip` is being reported as a `list` rather than an iterator-of-tuples; downstream `list(zip(...))[i][j]` doesn't expose per-position element narrowing.

### Cascade into containers (3 cases)

```python
# lists/nested
ls = [[func1], func2]               # heterogeneous: list, callable
a = ls[0]                           # GT: list      Predicted: callable, list
b = a[0]                            # GT: callable  Predicted: TypeError, callable
c = b()                             # GT: int       Predicted: TypeError, int
```

The `TypeError` halo comes from trying to call the leaked non-callable value.

---

## Bucket 3 — Heterogeneous container per-key/index narrowing (15 cases)

A container holds different types per key/index; GT expects per-position narrowing; we union.

### `lists/simple` (4 cases)

```python
def func1(): return 42
def func2(): return 42.5
def func3(): return "Hello from func3"

a = [func1, func2, func3]
c = a[0]()   # GT: int    Predicted: float, int, str
d = a[1]()   # GT: float  Predicted: float, int, str
e = a[2]()   # GT: str    Predicted: float, int, str

b = ["Hello"]
b[0] = func4
f = b[0]()   # GT: bool   Predicted: TypeError, bool  (str element still in union)
```

### `lists/slice:20`, `lists/unpacking:3` (4 cases)

```python
# lists/slice
ls = [func1, func2, func3]
ls2 = ls[1:3]
c = ls2[0]()   # GT: float  Predicted: float, int, str  (slice still has all elements)

# lists/unpacking
a = [1, 2.0, "hello"]
b, c, d = a    # GT: b=int, c=float, d=str  Predicted: float, int, str for all
```

### `dicts/call`, `dicts/type_coercion` (5 cases)

```python
# dicts/call
d = {"a": func1, 1: func2, 2: 3}
e = d["a"]()   # GT: str   Predicted: TypeError, int, str
f = d[1]()     # GT: int   Predicted: TypeError, int, str

# Plus 3 cases at line 12:
# d['a'], d[1] expected callable; d[2] expected int
# All three predicted: callable, int

# dicts/type_coercion
d = {1: func1, "1": func2}
e = d[1]()     # GT: str  Predicted: int, str
f = d["1"]()   # GT: int  Predicted: int, str
```

### `assignments/starred:21,22` (2 cases)

```python
a, *b, c = func1, func2, func3, func4
e = b[0]()   # GT: int    Predicted: float, int
f = b[1]()   # GT: float  Predicted: float, int
```

Same family — `b` is a list with heterogeneous element type; per-index access widens.

---

## Bucket 4 — Path-insensitive widening across call sites (10 cases)

Function with branching return reports the union at every caller; GT wants per-call-site narrowing based on argument values.

### `returns/multiple_types`

```python
def func(x):
    if x > 0:
        return x
    else:
        return "Invalid input"

a = func(5)    # GT: int   Predicted: int, str
b = func(-5)   # GT: str   Predicted: int, str
```

### `dicts/param_key`

```python
def func1(key="a"):
    return d[key]()

d = {"a": func2, "b": func3}        # func2 → str, func3 → int

e = func1()        # default key="a" → func2 → GT: str   Predicted: int, str
f = func1("b")     # key="b" → func3 → GT: int           Predicted: int, str
```

### `dicts/zip:6` × 3

```python
keys = ["a", "b", "c"]
values = [1, 2, 3]
my_dict = dict(zip(keys, values))
# my_dict['a'], ['b'], ['c'] each GT: int  Predicted: any
# (also depends on zip resolution)
```

This needs value-sensitive interpretation (a separate analysis functor, per earlier discussion).

---

## Bucket 5 — Container value rebind retains prior value (4 cases)

When `d["k"] = new_val` rebinds an existing key, GT expects only the new value; we keep both.

### `dicts/assign:16`, `dicts/update:15`, `dicts/nested:16` (3 cases)

```python
# dicts/assign
d = {"a": func1}     # func1 → str
d["a"] = func2       # rebind: func2 → int
e = d["a"]()         # GT: int   Predicted: int, str

# dicts/update
d = {"a": func1}            # func1 → int
d.update({"a": func2})       # rebind via .update()
e = d["a"]()                 # GT: str   Predicted: int, str

# dicts/nested
d = {"a": {"b": func1}}     # func1 → int
d["a"]["b"] = func2          # nested rebind
e = d["a"]["b"]()            # GT: str   Predicted: int  (the OPPOSITE shape — only new)
```

### `dicts/nested:12`

```python
d = {"a": {"b": func1}}
# d['a']['b']  GT: callable  Predicted: dict
# The outer access yields the inner dict, not its element.
```

---

## Bucket 6 — Decorator-replaced returns (3 cases)

Decorator returns a different function than the source; we report `any` (improvement from earlier `str` — at least honest now) but GT expects the replacement's return type.

### `decorators/nested`, `decorators/return`

```python
# decorators/nested
def func():
    def dec(f):
        return modified_inner
    def modified_inner():
        return 42

    @dec
    def inner():
        return "Hello from inner"

    return inner()                  # GT: int    Predicted: any

a = func()                          # GT: int    Predicted: any

# decorators/return
@func1()                            # call-decorator
def func2():
    return "Hello from func2"

a = func2()                         # GT: int    Predicted: any
```

---

## Bucket 7 — Class-specific gaps (6 cases)

### `classes/base_class_attr:20` — class attribute via super

```python
class A:
    class B:
        def __init__(self):
            self.a = "Hello __init__"
        def bfunc(self):
            return 42

class C(A.B):
    def __init__(self):
        super().__init__()           # super().__init__ sets self.a
    def cfunc(self):
        return self.a

c = C()
d = c.cfunc()                       # GT: str   Predicted: AttributeError
e = c.bfunc()                       # (line 21 OK or LM — not in TM bucket)
```

### `classes/static_method_call:10` and `functions/static:10` — static method dispatch

```python
class MyClass:
    @staticmethod
    def func():
        return "Hello from func"

a = MyClass.func()                  # GT: str   Predicted: TypeError

# functions/static (same pattern, different snippet):
class MyClass:
    @staticmethod
    def my_static_method(x, y):
        return x + y

result = MyClass.my_static_method(2, 3)   # GT: int  Predicted: TypeError
```

`@staticmethod` decorator + `ClassName.method(...)` dispatch isn't routed correctly.

### `mro/parents_same_superclass:29` — MRO chooses wrong parent

```python
class A:
    def func(self):
        return "Hello from func in classA"

class B(A): pass

class C(A):
    def func(self):
        return 42

class D(B, C): pass    # MRO: D -> B -> C -> A; func resolves through C

d = D()
e = d.func()           # GT: int   Predicted: str  (picks A's version, not C's)
```

### `mro/super_call:20` — super() chain not threaded

```python
class A:
    def func(self):
        return "Hello from class A"

class B(A):
    def func(self):
        return super().func()

class C(B):
    def func(self):
        return super().func()

c = C()
d = c.func()           # GT: str   Predicted: any
```

---

## Bucket 8 — Implicit-None / empty returns (3 cases)

### `builtins/map:2`, `decorators/classes:4`, `returns/object:10`

```python
# builtins/map
def func(x):
    return x                        # GT(return func): float, int, str — Predicted: []
# Empty prediction; the function reaches into the iterable but doesn't surface a return.

# decorators/classes
def my_decorator(cls):
    class NewClass(cls):
        def my_method(self):
            return "Hello from my_method in NewClass"
    return NewClass                 # GT(return my_decorator): type — Predicted: []

# returns/object
class Person:
    def __init__(self, name, age):
        self.name = name
        self.age = age

def func():
    return Person("Alice", 25)      # GT(return func): Person — Predicted: []
```

Three different shapes, same surface symptom: the function's return slot has no element. Likely some instantiation-tracking gap (function never observed being called from a position where the return matters, or the return wire doesn't flow through to the FunctionView.instantiations[].ret slot).

---

## Bucket 9 — Dynamic codegen (6 cases) — out of scope per earlier discussion

`dynamic/compile`, `dynamic/eval`, `dynamic/exec` produce `TypeError` / `NameError` for the dynamically-computed values. Skip.

---

## Other miscellaneous (3 cases)

### `lists/comprehension_val` and `lists/nested_comprehension` — comprehension body call leaks

```python
def func(a):                        # GT(return func): int — Predicted: TypeError
    return a + 1                    # GT(parameter a): int — Predicted: TypeError

ls = [func(a) for a in range(10)]
```

The comprehension translates, but the inner `func(a)` call still produces `TypeError`. Could be related to `range` not being modeled (Tier 3 builtin), or to comprehension-scope parameter binding being a fresh instance of the multi-parameter bug.

### `lists/param_index:8` — `any` leaking on parameter

```python
def func1(key):                     # GT: int   Predicted: any, int
    return ls[key]()
```

A stray `any` on the parameter wire after narrowing.

### `dicts/new_key_param:15`

```python
def func(key="a"):
    d[key] = func2

d = {}
func()
e = d["a"]()                        # GT: str   Predicted: any
```

The dict-set-via-param-key doesn't flow the typing through.

---

## Summary table

| Bucket | Count | Action |
|---|---:|---|
| 1. Multi-parameter NameError | 17 | Likely regression — investigate binding loop |
| 2. `zip` / `map` signatures + cascade | 13 | Land builtin signatures |
| 3. Heterogeneous container narrowing | 15 | Per-key/index sparse-map element typing |
| 4. Path-insensitive widening | 10 | Value-sensitive interpretation (separate functor) |
| 5. Container rebind | 4 | `STORE` to subscript should replace, not union |
| 6. Decorator-replaced returns | 3 | Decorator semantics (in progress) |
| 7. Class gaps (attr / static / super / MRO) | 6 | Various class-side analysis work |
| 8. Implicit-None / empty returns | 3 | Investigate why ret slot lacks element |
| 9. Dynamic codegen | 6 | Out of scope |
| 10. Misc (comprehension, param `any`, dict-param) | 4 | Per-case |

**Top three to investigate:** the multi-parameter regression (1), `zip`/`map` (2), heterogeneous container narrowing (3) — together ~45 of the 78 TYPE_MISS cases.
