# TypeEvalPy micro — Targets for Translation & Analysis

Cases the best published static tool (HeaderGen, 580/850 = 68.2% strict) still misses on TypeEvalPy's micro benchmark. Compiled as a triage list for translation and analysis work: each section is a concrete pattern the GT scores against, with snippet source and expectation.

- **Run scored:** HeaderGen on micro · 580/850 EXACT · 190 LOCATION_MISS · 80 TYPE_MISS
- **Scope:** miss categories where the analysis is tractable in principle. Dynamic-codegen snippets (`dynamic/compile`, `dynamic/eval`, `dynamic/exec`) are excluded as out-of-scope for static.
- **GT location convention:** TypeEvalPy ground truth is keyed by `(file, line, col_offset, kind, name)` with both line and col 1-indexed; col points at the start of the named identifier.

## Bucket summary (270 misses, 264 in-scope)

| # | Bucket | HeaderGen misses | Notes |
|---:|---|---:|---|
| 1 | For-loop iterator variable binding | ~30 | `for x in iter:` — `x` takes iterator's element type |
| 2 | Lambda body inference | 22 | Body of `lambda x: <expr>` + the call result |
| 3 | Decorators (wrapper or replace-fn) | 17 | `@dec` applied, wrapper's return type not threaded |
| 4 | Container element through writes | ~15 | `d["k"] = v; e = d["k"]` chains |
| 5 | Builtin function signatures | 10–15 | `map`, `zip`, `min/max/sum/len/sorted/any/all`, `reduce`, `itertools.*`, str/list methods |
| 6 | MRO parent-union | 8 | Multiple parents or overrides supply the method |
| 7 | Tuple/list unpacking | 8 | `a, b = pair`, `*xs, y = lst`, nested `(a,b),(c,d) = lst` |
| 8 | Generator return typing | 5 | `def f(): yield x` → return type `generator` |
| 9 | Comprehension element typing | 6 | `[f(a) for a in r]` — bound name `a` doesn't surface |
| 10 | `super().method()` resolution | 3 | Parent method's return type via super |
| 11 | Augmented assignment | 4 | `a += 1`, `a *= 2` |
| 12 | Walrus | 3 | `(x := expr)` rebind |
| 13 | Path-insensitive value narrowing | 5 | `if x>0: int else: str` — caller-side narrowing |
| 14 | External-module call results | 12 | Cross-module flow (separate concern) |

Per-category sections below have representative source. Where GT expectations are shown inline as `# GT: ...` they are paraphrased from `main_gt.json`.

---

## 1. For-loop iterator variable binding

`for x in iterable:` should bind `x` to the iterator's element type, and downstream uses of `x` should inherit that type. This is the single biggest miss bucket (~30 LOCATION_MISS entries spread across `generators/iter_param`, `generators/iter_return`, `generators/iterable`, `generators/iterable_assigned`, `assignments/generators`, `builtins/itertools`).

### `generators/iter_param`

```python
def func(c):
    output_list = [i for i in c]   # GT(parameter c, line 4): int
    return output_list              # GT(return func): int (the list element type from Cls iteration)


class Cls:
    def __init__(self, max=0):
        self.max = max
    def __iter__(self):
        self.n = 0
        return self
    def __next__(self):
        if self.n > self.max:
            raise StopIteration
        result = 2**self.n          # GT(variable result): int
        self.n += 1                 # GT(variable self.n): int
        return result               # GT(return __next__): int


a = func(Cls(2))                    # GT(variable a): int
```

Why it's a target: the loop variable's type is `__next__`'s return type. Recognizing this is mechanical once `__iter__`/`__next__` protocol is modeled. HeaderGen returns nothing for any of the 10 GT entries in this snippet.

### `generators/iterable_assigned` (same pattern, 7 LOCATION_MISS)

Identical shape — iterator object assigned to a variable, then `for x in iter:` over it.

---

## 2. Lambda body inference

All 22 `lambdas/*` misses come from one root cause: the body of a lambda isn't type-inferred and the call result isn't propagated.

### `lambdas/call` (basic)

```python
x = lambda x: x + 1     # GT(variable x, outer): callable
a = x(1)                # GT(variable a): int; GT(parameter x of lambda): int
```

HeaderGen LOCATION_MISS on all three GT entries.

### `lambdas/chained_calls` (compositional)

```python
def func3(a):
    return a(1)             # GT(parameter a): callable; GT(return func3): int

def func2(a, b):
    a(1)                    # GT(parameter a): callable
    return func3(b)         # GT(return func2): int; GT(parameter b): callable

def func1(a, b, c):
    a(1)                    # GT(parameter a): callable
    return func2(b, c)      # GT(return func1): int

d = func1(lambda x: x + 1, lambda x: x + 2, lambda x: x + 3)   # GT(variable d): int
```

Every parameter and every return is `callable` or `int`. HeaderGen returns nothing for the parameters and `Nonetype` for the returns — it doesn't trace the lambda call result through `func3`'s `a(1)`.

### `lambdas/calls_parameter` (lambda calls its parameter)

```python
def func1(): return 42
def func2(): return "Hello from func2"

x = lambda x: x()                   # GT(variable x outer): callable
a = x(func1)                        # GT: int
b = x(func2)                        # GT: str  ← TYPE_MISS: HeaderGen got Nonetype on both
```

Tractable because lambdas are syntactically just anonymous `def`s with one return expression.

---

## 3. Decorators

17 misses fall in two sub-patterns. We hit the same root cause on the Archway side, so these double as our own targets.

### Sub-pattern A: wrapper has implicit return

```python
# decorators/assigned
def dec1(f):
    def wrapper(a, b):
        result = f(a, b)
        return result
    return wrapper

a = dec1

@a
def func(a, b):
    return a + b          # GT(return func): str (when called with strings)

c = func("Hello", "world")   # GT(variable c): str
```

HeaderGen predicts `Nonetype` for `c` and the return — it accepts `@a` but doesn't thread the inner wrapper's return type out to the decorated name. Same shape in `decorators/param_call`, `decorators/return_different_func`.

### Sub-pattern B: wrapper returns a different function

```python
# decorators/nested
def func():
    def dec(f):
        return modified_inner            # decorator returns a DIFFERENT function

    def modified_inner():
        return 42                        # GT(return modified_inner): int

    @dec
    def inner():
        return "Hello from inner"        # GT(return inner): str (the SOURCE return)

    return inner()                       # GT(return func): int ← `inner` was rewritten

a = func()                               # GT(variable a): int
```

HeaderGen predicts `str` for both `func`'s return and `a` — it reports the source function's return type, missing that the decorator replaced the body. Same shape in `decorators/nested_decorators`, `decorators/return`.

---

## 4. Container element through writes

`d["k"] = v; e = d["k"]` — the GT tracks per-key types after each write. HeaderGen LOCATION_MISS on all subscript-read GT entries.

### `dicts/assign`

```python
def func1(): return "Hello from func1"
def func2(): return 42

d = {"a": func1}            # GT(variable d['a']): callable

d["a"] = func2              # rebind: GT(variable d['a'] after this line): callable

e = d["a"]()                # GT(variable e): int ← func2's return after rebind
func1()
```

### `dicts/nested` (chained subscript LHS)

```python
def func1(): return 42
def func2(): return "Hello from func2"

d = {"a": {"b": func1}}     # GT(variable d['a']['b']): callable

d["a"]["b"] = func2         # rebind nested

e = d["a"]["b"]()           # GT(variable e): str
```

### `dicts/merge` (dict-merge preserves per-key element types)

```python
dict1 = {"a": 1, "b": 2}
dict2 = {"c": 3, "d": 4}
merged_dict = {**dict1, **dict2}
# GT(variable dict1['a']): int, dict1['b']: int
# GT(variable merged_dict['a'..'d']): int
```

Same idea with `dict(zip(keys, values))` in `dicts/zip` — each key in the constructed dict should carry the corresponding value's type.

### `lists/simple` (list-of-callables, indexed call)

```python
def func1(): return 42
def func2(): return 42.5
def func3(): return "Hello from func3"

a = [func1, func2, func3]
c = a[0]()           # GT: int
d = a[1]()           # GT: float
e = a[2]()           # GT: str

def func4(): return True

b = ["Hello"]
b[0] = func4         # rebind by index
f = b[0]()           # GT: bool ← TYPE_MISS: HeaderGen got callable
```

---

## 5. Builtin function signatures

Specific built-ins that the GT scores against:

### `builtins/functions` (sum/min/max/len/sorted/any/all)

```python
my_list = [1, 2]

length = len(my_list)        # GT: int
total  = sum(my_list)        # GT: int
largest = max(my_list)       # GT: int  ← TYPE_MISS: HeaderGen returns "max" (the function object)
smallest = min(my_list)      # GT: int  ← TYPE_MISS: HeaderGen returns "min"
sorted_list = sorted(my_list)   # GT: list
any_list = any([1, True])       # GT: bool
all_list = all([1, True])       # GT: bool
```

### `builtins/map`

```python
def func(x): return x
res = map(func, [1, "Hello", 3.0])  # GT(variable res): the iterator; GT(return func): int|str|float
x, y, z = res                       # GT(variable x): int, y: str, z: float
```

GT expects `map` to expose the union of element types at each unpacked position. HeaderGen LOCATION_MISS on all four destructured variables.

### `builtins/zip`

```python
names = ["Alice", "Bob"]
ages = [30, 25]
combined = zip(names, ages)     # GT(variable combined): zip-iterator (element: tuple)
result = list(combined)         # GT(variable result): list of tuples
```

### `builtins/functools`

```python
from functools import reduce

def multiply(x, y): return x * y     # GT(return multiply): int

numbers = [1, 2]
product = reduce(multiply, numbers)  # GT(variable product): int ← TYPE_MISS: HeaderGen returns "functools.reduce"
```

### `builtins/types` (str/list methods)

```python
a = " ".join(["1", "2", "3"])    # GT: str
b = "a b".split(" ")             # GT: list
```

---

## 6. MRO parent-union

When multiple parents or overrides can supply a method, GT expects the union of all reachable return types. HeaderGen picks one.

### `mro/two_parents_method_defined`

```python
class A:
    def __init__(self): pass
    def func(self):
        return 42.5           # GT(return A.func): float

class B:
    def func(self):
        return 42             # GT(return B.func): int

class C(A, B):
    def __init__(self): pass
    def func(self):
        return "Hello from func in class C"   # GT(return C.func): str

c = C()
d = c.func()                  # GT(variable d): str (C.func wins)
A().func(); B().func()        # GT for these instantiations: float and int respectively
```

HeaderGen TYPE_MISS: returns `float` for `A.func` only and `int` for `B.func` only — but the cross-instantiation summary that GT expects requires per-call-site narrowing too. Also `mro/parents_same_superclass`, `mro/self_assignment`, `mro/two_parents` follow this pattern.

### `classes/inheritance_overriding` (parent + child returns are both expected)

```python
class MyClass:
    def func(self):
        return "Hello from func in MyClass"   # GT(return MyClass.func): str

class MySubClass(MyClass):
    def func(self):
        return 42                              # GT(return MySubClass.func): int

MyClass().func()
a = MySubClass()
b = a.func()                # GT(variable b): int
```

For the overridden return-GT, the GT marks the *combined* `["int", "str"]` — i.e. across all callers, both branches are valid. Tools that report only the bound class's override miss the parent.

### `classes/base_class_calls_child` (parent calls overridden child method)

```python
class A:
    def func(self):
        return self.child()          # GT(return A.func): callable (the bound method)

class B(A):
    def __init__(self): self.child = self.func2
    def func2(self): return "Hello from class B"   # GT: str

class C(A):
    def __init__(self): self.child = self.func2
    def func2(self): return 42                     # GT: int

b = B(); d = b.func()          # GT(variable d): str   ← HeaderGen got "int|str"
c = C(); e = c.func()          # GT(variable e): int   ← HeaderGen got "int|str"
```

Each instance carries its own `self.child`. GT keys on the specific instance.

---

## 7. Tuple/list unpacking

8 misses across `assignments/nested_unpack`, `assignments/starred`, `lists/unpacking`.

### `assignments/nested_unpack`

```python
def func1(): return "Hello from func1"
def func2(): return 42
def func3(): return 42.5
def func4(): return [2, 4]

(a, b), (c, d) = [(func1, func2), (func3, func4)]
# GT(variable a..d): callable each
a(); b(); c(); d();
```

### `assignments/starred`

```python
a, *b, c = func1, func2, func3, func4
# GT(variable a): callable; b: list (of callables); c: callable

d = a()                # GT: str
e = b[0]()             # GT: int (func2 result)
f = b[1]()             # GT: float
g = c()                # GT: list
```

HeaderGen TYPE_MISS on `b` (predicted `float` instead of `list`) and LOCATION_MISS on the others.

### `lists/unpacking` (heterogeneous list destructuring)

```python
a = [1, 2.0, "hello"]
b, c, d = a            # GT: b=int, c=float, d=str
```

GT distributes positionally; HeaderGen LOCATION_MISS on all three.

---

## 8. Generator return typing

5 TYPE_MISS. `def f(): yield x` should be typed `generator` (whole-function-level), not by what's yielded.

### `generators/yield_function`

```python
def func2(): return 5

def func1(n):              # GT(return func1): generator   ← HeaderGen got "callable"
    num = 0
    while num < n:
        yield func2
        num += 1

for i in func1(10):        # GT(variable i): callable
    try:
        a += i()           # GT(variable a): int
    except NameError:
        a = i()
```

### `generators/yield_next`

```python
def squares():             # GT(return squares): generator   ← HeaderGen got "int"
    n = 1
    while True:
        yield n**2
        n += 1

gen = squares()            # GT(variable gen): generator    ← HeaderGen got "int"

for i in range(5):
    try:
        a += next(gen)     # GT(variable a): int            ← TYPE_MISS: HeaderGen got "next" (the function)
    except NameError:
        a = next(gen)
```

Recognition is syntactic — a function containing `yield` is a generator-producing function.

---

## 9. Comprehension element typing

The comprehension bound name doesn't surface as an annotated location for HeaderGen.

### `lists/comprehension_val`

```python
def func(a):                   # GT(parameter a): int; GT(return func): int (← TYPE_MISS: HeaderGen got Nonetype)
    return a + 1

ls = [func(a) for a in range(10)]   # GT(variable a, line 8): int  ← LOCATION_MISS
```

### `lists/nested_comprehension`

```python
def func1(a): return a + 1     # GT(parameter a): int; GT(return func1): int
def func2(a): return a + 1     # GT(parameter a): int; GT(return func2): int

c = [func1(a) for a in [func2(b) for b in range(10)]]
# GT(variable a, b): int each
```

`a` and `b` bind to `int` via `range`'s element type. Same as for-loop binding, plus comprehension scoping.

---

## 10. `super().method()`

### `mro/super_call`

```python
class A:
    def func(self):
        return "Hello from class A"

class B(A):
    def func(self):
        return super().func()        # GT(return B.func): str

class C(B):
    def func(self):
        return super().func()        # GT(return C.func): str

c = C()
d = c.func()                         # GT(variable d): str
```

All three GT entries return `Nonetype` from HeaderGen — `super().func()` isn't resolved up the chain. Tractable: walk MRO, call the matching method on the parent class.

---

## 11. Augmented assignment

### `assignments/augmented`

```python
def func1(a):
    a += 3                  # GT(parameter a, line 5): int; GT(variable a, line 6): int
    a *= 2                  # GT(variable a, line 7): int
    return a                # GT(return func1): int   ← TYPE_MISS: HeaderGen got Nonetype

b = func1(5)                # GT(variable b): int     ← TYPE_MISS: HeaderGen got Nonetype
```

`a` stays `int` across `+=`/`*=` because the operands are `int`. Should be derivable from the operator type table.

---

## 12. Walrus

### `assignments/walrus`

```python
def count_words(string):
    words = string.split()              # GT(variable words): list
    word_count = 0                      # GT(variable word_count): int

    while words and (word := words.pop()):   # GT(variable word): str
        print(word)
        word_count += 1

    return word_count                   # GT(return count_words): int

a = count_words("Hello Python")         # GT(variable a): int
```

`(word := words.pop())` rebinds `word` in the enclosing scope to the element type of `words`. HeaderGen LOCATION_MISS on `words`, `word`, and one of the `word_count` GT entries.

---

## 13. Path-insensitive value narrowing — *harder*

Cases where GT expects per-call-site narrowing based on which branch fires. Likely needs a value-sensitive interpretation layer.

### `builtins/switch`

```python
def func(value):
    match value:
        case "case1":
            return 42                  # int branch
        case "case2":
            return "hello this is case2"
        case _:
            return "unknown type"

a = func("case1")     # GT: int   ← HeaderGen got int|str
b = func("case2")     # GT: str   ← HeaderGen got int|str
c = func("case3")     # GT: str   ← HeaderGen got int|str
```

GT expects the caller's literal argument to narrow the match arm. Pattern is identical to `returns/multiple_types` (the `if x>0: int else: str` snippet).

---

## 14. External module call results

12 LOCATION_MISS / TYPE_MISS where the GT references a type produced by `typeevalpy_external_module.ext.*`. These need a Python-package layout where `ext.py` is importable and its definitions can be analyzed cross-module. Listing for completeness; treat as a separate concern from the in-file inference cases above.

Snippets: `external/*` (12 misses, all surface as either `LOCATION_MISS` or a TYPE_MISS where HeaderGen reports the qualified-name string instead of the resolved type).

---

## How to consume this doc

- **Translation agents**: every snippet here is a current TypeEvalPy micro test case (`vendor/TypeEvalPy/micro-benchmark/python_features/<bucket>/<name>/main.py`). The translation can succeed against any of them; whether the resulting wires let the analysis answer the GT is the goal.
- **Analysis agents**: for each in-scope bucket, the source + GT comment shows what type the wire must carry at the GT location. Use the snippet as a unit test for the analysis pass that closes the gap.
- **Triage**: buckets 1–8 (LOCATION_MISS-dominant, ~110 misses combined) are the highest-leverage targets — closing them roughly tracks toward HeaderGen-equivalent on the strict scorer.
