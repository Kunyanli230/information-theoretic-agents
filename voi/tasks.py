"""40 synthetic bug-fix tasks. Each: fixed source, (correct, buggy) replacement, visible test, hidden tests."""
T = []
def add(name, src, good, bad, visible, hidden):
    assert good in src, name
    T.append(dict(id=f"T{len(T)+1:02d}", name=name, fixed=src, buggy=src.replace(good, bad, 1),
                  visible=visible, hidden=hidden))

add("sum_to_n", "def sum_to_n(n):\n    total = 0\n    for i in range(1, n + 1):\n        total += i\n    return total\n",
    "range(1, n + 1)", "range(1, n)", "assert sum_to_n(3) == 6",
    ["assert sum_to_n(0) == 0","assert sum_to_n(1) == 1","assert sum_to_n(10) == 55","assert sum_to_n(3) == 6"])
add("max_of", "def max_of(xs):\n    best = xs[0]\n    for x in xs:\n        if x > best:\n            best = x\n    return best\n",
    "x > best", "x < best", "assert max_of([1, 5, 2]) == 5",
    ["assert max_of([3]) == 3","assert max_of([-1,-5]) == -1","assert max_of([1,5,2]) == 5","assert max_of([2,2,9,0]) == 9"])
add("is_even", "def is_even(n):\n    return n % 2 == 0\n", "== 0", "== 1", "assert is_even(4)",
    ["assert is_even(0)","assert not is_even(3)","assert is_even(-2)","assert is_even(4)"])
add("average", "def average(xs):\n    if not xs:\n        return 0.0\n    return sum(xs) / len(xs)\n", "sum(xs) / len(xs)", "sum(xs) // len(xs)",
    "assert average([1, 2]) == 1.5", ["assert average([]) == 0.0","assert average([1,2]) == 1.5","assert average([4]) == 4","assert abs(average([1,2,2]) - 5/3) < 1e-9"])
add("count_vowels", "def count_vowels(s):\n    return sum(1 for c in s.lower() if c in 'aeiou')\n", "s.lower()", "s",
    "assert count_vowels('AEi') == 3", ["assert count_vowels('') == 0","assert count_vowels('AEi') == 3","assert count_vowels('xyz') == 0","assert count_vowels('Hello World') == 3"])
add("reverse_words", "def reverse_words(s):\n    return ' '.join(reversed(s.split()))\n", "reversed(s.split())", "s.split()",
    "assert reverse_words('a b') == 'b a'", ["assert reverse_words('a b') == 'b a'","assert reverse_words('x') == 'x'","assert reverse_words('one two three') == 'three two one'"])
add("factorial", "def factorial(n):\n    result = 1\n    for i in range(2, n + 1):\n        result *= i\n    return result\n", "result = 1", "result = 0",
    "assert factorial(3) == 6", ["assert factorial(0) == 1","assert factorial(1) == 1","assert factorial(5) == 120","assert factorial(3) == 6"])
add("clamp", "def clamp(x, lo, hi):\n    if x < lo:\n        return lo\n    if x > hi:\n        return hi\n    return x\n", "return hi", "return lo",
    "assert clamp(10, 0, 5) == 5", ["assert clamp(10,0,5) == 5","assert clamp(-1,0,5) == 0","assert clamp(3,0,5) == 3"])
add("last_n", "def last_n(xs, n):\n    if n <= 0:\n        return []\n    return xs[-n:]\n", "if n <= 0:\n        return []\n    ", "",
    "assert last_n([1, 2, 3], 0) == []", ["assert last_n([1,2,3],0) == []","assert last_n([1,2,3],2) == [2,3]","assert last_n([1],5) == [1]"])
add("fib", "def fib(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\n", "a, b = b, a + b", "a, b = b, a * b",
    "assert fib(5) == 5", ["assert fib(0) == 0","assert fib(1) == 1","assert fib(5) == 5","assert fib(10) == 55"])
add("append_item", "def append_item(x, xs=None):\n    if xs is None:\n        xs = []\n    xs.append(x)\n    return xs\n", "xs=None):\n    if xs is None:\n        xs = []\n", "xs=[]):\n",
    "append_item(1)\nassert append_item(2) == [2]", ["append_item(1)\nassert append_item(2) == [2]","assert append_item(1, [0]) == [0, 1]"])
add("is_palindrome", "def is_palindrome(s):\n    t = ''.join(c.lower() for c in s if c.isalnum())\n    return t == t[::-1]\n", "c.lower()", "c",
    "assert is_palindrome('Aba')", ["assert is_palindrome('Aba')","assert is_palindrome('A man, a plan, a canal: Panama')","assert not is_palindrome('abc')","assert is_palindrome('')"])
add("count_occ", "def count_occ(xs, v):\n    c = 0\n    for x in xs:\n        if x == v:\n            c += 1\n    return c\n", "c += 1", "c = 1",
    "assert count_occ([1, 1, 2], 1) == 2", ["assert count_occ([1,1,2],1) == 2","assert count_occ([],1) == 0","assert count_occ([3,3,3],3) == 3"])
add("first_index", "def first_index(xs, v):\n    for i, x in enumerate(xs):\n        if x == v:\n            return i\n    return -1\n", "return -1", "return 0",
    "assert first_index([1, 2], 9) == -1", ["assert first_index([1,2],9) == -1","assert first_index([5,6,5],5) == 0","assert first_index([5,6],6) == 1"])
add("celsius_to_f", "def celsius_to_f(c):\n    return c * 9 / 5 + 32\n", "c * 9 / 5 + 32", "(c + 32) * 9 / 5",
    "assert celsius_to_f(100) == 212", ["assert celsius_to_f(0) == 32","assert celsius_to_f(100) == 212","assert celsius_to_f(-40) == -40"])
add("unique_sorted", "def unique_sorted(xs):\n    return sorted(set(xs))\n", "sorted(set(xs))", "list(set(xs))",
    "assert unique_sorted(['b', 'c', 'a', 'b', 'd']) == ['a', 'b', 'c', 'd']", ["assert unique_sorted([3,1,3,2]) == [1,2,3]","assert unique_sorted([]) == []","assert unique_sorted([10,5,10,7,1]) == [1,5,7,10]"])
add("power", "def power(b, e):\n    r = 1\n    for _ in range(e):\n        r *= b\n    return r\n", "r *= b", "r *= e",
    "assert power(2, 3) == 8", ["assert power(2,3) == 8","assert power(5,0) == 1","assert power(3,2) == 9"])
add("chunk", "def chunk(xs, k):\n    return [xs[i:i + k] for i in range(0, len(xs), k)]\n", "range(0, len(xs), k)", "range(0, len(xs) - k, k)",
    "assert chunk([1, 2, 3], 2) == [[1, 2], [3]]", ["assert chunk([1,2,3],2) == [[1,2],[3]]","assert chunk([],2) == []","assert chunk([1,2,3,4],2) == [[1,2],[3,4]]"])
add("safe_div", "def safe_div(a, b):\n    if b == 0:\n        return None\n    return a / b\n", "if b == 0:", "if a == 0:",
    "assert safe_div(1, 0) is None", ["assert safe_div(1,0) is None","assert safe_div(0,5) == 0","assert safe_div(6,3) == 2"])
add("capitalize_words", "def capitalize_words(s):\n    return ' '.join(w[:1].upper() + w[1:] for w in s.split(' '))\n", "w[1:]", "w[2:]",
    "assert capitalize_words('hi there') == 'Hi There'", ["assert capitalize_words('hi there') == 'Hi There'","assert capitalize_words('a') == 'A'","assert capitalize_words('abc def') == 'Abc Def'"])
add("min_index", "def min_index(xs):\n    best = 0\n    for i in range(1, len(xs)):\n        if xs[i] < xs[best]:\n            best = i\n    return best\n", "xs[i] < xs[best]", "xs[i] < xs[i - 1]",
    "assert min_index([2, 0, 3, 1]) == 1", ["assert min_index([3,1,2]) == 1","assert min_index([5,1,4,3]) == 1","assert min_index([2]) == 0","assert min_index([1,3,2]) == 0"])
add("flatten", "def flatten(xss):\n    out = []\n    for xs in xss:\n        out.extend(xs)\n    return out\n", "out.extend(xs)", "out.append(xs)",
    "assert flatten([[1], [2, 3]]) == [1, 2, 3]", ["assert flatten([[1],[2,3]]) == [1,2,3]","assert flatten([]) == []","assert flatten([[],[4]]) == [4]"])
add("in_range", "def in_range(x, lo, hi):\n    return lo <= x <= hi\n", "lo <= x <= hi", "lo < x < hi",
    "assert in_range(5, 5, 10)", ["assert in_range(5,5,10)","assert in_range(10,5,10)","assert not in_range(11,5,10)","assert in_range(7,5,10)"])
add("word_count", "def word_count(s):\n    d = {}\n    for w in s.split():\n        d[w] = d.get(w, 0) + 1\n    return d\n", "d.get(w, 0) + 1", "1",
    "assert word_count('a a b') == {'a': 2, 'b': 1}", ["assert word_count('a a b') == {'a':2,'b':1}","assert word_count('') == {}","assert word_count('x x x') == {'x':3}"])
add("gcd", "def gcd(a, b):\n    while b:\n        a, b = b, a % b\n    return a\n", "return a", "return b",
    "assert gcd(12, 8) == 4", ["assert gcd(12,8) == 4","assert gcd(7,3) == 1","assert gcd(10,0) == 10"])
add("strip_prefix", "def strip_prefix(s, p):\n    if s.startswith(p):\n        return s[len(p):]\n    return s\n", "s[len(p):]", "s[len(p) + 1:]",
    "assert strip_prefix('foobar', 'foo') == 'bar'", ["assert strip_prefix('foobar','foo') == 'bar'","assert strip_prefix('bar','foo') == 'bar'","assert strip_prefix('aab','a') == 'ab'"])
add("running_sum", "def running_sum(xs):\n    out, s = [], 0\n    for x in xs:\n        s += x\n        out.append(s)\n    return out\n", "        s += x\n        out.append(s)", "        out.append(s)\n        s += x",
    "assert running_sum([1, 2, 3]) == [1, 3, 6]", ["assert running_sum([1,2,3]) == [1,3,6]","assert running_sum([]) == []","assert running_sum([5]) == [5]"])
add("median", "def median(xs):\n    s = sorted(xs)\n    n = len(s)\n    if n % 2:\n        return s[n // 2]\n    return (s[n // 2 - 1] + s[n // 2]) / 2\n", "s = sorted(xs)", "s = xs",
    "assert median([3, 1, 2]) == 2", ["assert median([3,1,2]) == 2","assert median([4,1,3,2]) == 2.5","assert median([5]) == 5"])
add("all_positive", "def all_positive(xs):\n    for x in xs:\n        if x <= 0:\n            return False\n    return True\n", "x <= 0", "x < 0",
    "assert not all_positive([1, 0])", ["assert not all_positive([1,0])","assert all_positive([])","assert all_positive([1,2])","assert not all_positive([-1])"])
add("dedupe_keep_order", "def dedupe_keep_order(xs):\n    seen, out = set(), []\n    for x in xs:\n        if x not in seen:\n            seen.add(x)\n            out.append(x)\n    return out\n", "            seen.add(x)\n", "",
    "assert dedupe_keep_order([1, 1, 2]) == [1, 2]", ["assert dedupe_keep_order([1,1,2]) == [1,2]","assert dedupe_keep_order([3,1,3,1]) == [3,1]","assert dedupe_keep_order([]) == []"])
add("digits_sum", "def digits_sum(n):\n    n = abs(n)\n    s = 0\n    while n:\n        s += n % 10\n        n //= 10\n    return s\n", "n //= 10", "n /= 10",
    "assert digits_sum(123) == 6", ["assert digits_sum(123) == 6","assert digits_sum(0) == 0","assert digits_sum(-45) == 9"])
add("merge_dicts", "def merge_dicts(a, b):\n    out = dict(a)\n    out.update(b)\n    return out\n", "out = dict(a)\n    out.update(b)", "out = dict(b)\n    out.update(a)",
    "assert merge_dicts({'x': 1}, {'x': 2}) == {'x': 2}", ["assert merge_dicts({'x':1},{'x':2}) == {'x':2}","assert merge_dicts({},{'y':1}) == {'y':1}","assert merge_dicts({'a':1},{'b':2}) == {'a':1,'b':2}"])
add("nth_char", "def nth_char(s, n):\n    if 0 <= n < len(s):\n        return s[n]\n    return ''\n", "0 <= n < len(s)", "0 <= n <= len(s)",
    "assert nth_char('ab', 2) == ''", ["assert nth_char('ab',2) == ''","assert nth_char('ab',1) == 'b'","assert nth_char('',0) == ''","assert nth_char('ab',-1) == ''"])
add("count_upper", "def count_upper(s):\n    return sum(1 for c in s if c.isupper())\n", "c.isupper()", "c.islower()",
    "assert count_upper('AbC') == 2", ["assert count_upper('AbC') == 2","assert count_upper('') == 0","assert count_upper('abc') == 0"])
add("pairwise_diff", "def pairwise_diff(xs):\n    return [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]\n", "xs[i + 1] - xs[i]", "xs[i] - xs[i + 1]",
    "assert pairwise_diff([1, 4, 6]) == [3, 2]", ["assert pairwise_diff([1,4,6]) == [3,2]","assert pairwise_diff([5]) == []","assert pairwise_diff([0,-1]) == [-1]"])
add("rotate_left", "def rotate_left(xs, k):\n    if not xs:\n        return []\n    k %= len(xs)\n    return xs[k:] + xs[:k]\n", "    k %= len(xs)\n", "",
    "assert rotate_left([1, 2, 3], 4) == [2, 3, 1]", ["assert rotate_left([1,2,3],4) == [2,3,1]","assert rotate_left([1,2,3],1) == [2,3,1]","assert rotate_left([],3) == []"])
add("title_len", "def longest_word(s):\n    words = s.split()\n    if not words:\n        return ''\n    return max(words, key=len)\n", "key=len", "key=str.lower",
    "assert longest_word('zz bbbb') == 'bbbb'", ["assert longest_word('zz bbbb') == 'bbbb'","assert longest_word('') == ''","assert longest_word('zz bbbb') == 'bbbb'"])
add("sign", "def sign(x):\n    if x > 0:\n        return 1\n    if x < 0:\n        return -1\n    return 0\n", "if x < 0:", "if x <= 0:",
    "assert sign(0) == 0", ["assert sign(0) == 0","assert sign(-3) == -1","assert sign(2) == 1"])
add("percent", "def percent(part, whole):\n    if whole == 0:\n        return 0.0\n    return 100.0 * part / whole\n", "100.0 * part / whole", "100.0 * whole / part",
    "assert percent(1, 4) == 25.0", ["assert percent(1,4) == 25.0","assert percent(0,5) == 0.0","assert percent(3,0) == 0.0"])
add("second_largest", "def second_largest(xs):\n    u = sorted(set(xs))\n    return u[-2] if len(u) >= 2 else None\n", "u[-2]", "u[1]",
    "assert second_largest([1, 9, 3, 5]) == 5", ["assert second_largest([1,5,3]) == 3","assert second_largest([2,2]) is None","assert second_largest([9,1,9,4,7]) == 7"])
assert len(T) == 40
