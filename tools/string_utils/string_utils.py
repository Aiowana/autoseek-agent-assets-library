import re

def reverse_string(s):
    return s[::-1]

def count_words(text):
    words = text.split()
    return len(words)

def to_snake_case(s):
    s = re.sub(r"([A-Z])", r"_\1", s)
    return s.lower().lstrip("_")
