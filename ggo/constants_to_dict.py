import re

path = './goban_gtk4_modular.py'
with open(path, 'rt') as fp:
    data = fp.read()
matcher_1 = re.compile(r'(?:[A-Z]+_)+[A-Z]+')
constants = set(matcher_1.findall(data))
# print(*constants, sep='\n')
matcher_2 = re.compile('(?<!")(%s)(?!")'%('|'.join(
    sorted(constants, key=len, reverse=True)
)))
replace_fn = lambda m:'DEFAULT_STYLE[\'%s\']'%(m.group(1).lower())
data = matcher_2.sub(replace_fn, data)
with open(path, 'wt') as fp:
    fp.write(data)