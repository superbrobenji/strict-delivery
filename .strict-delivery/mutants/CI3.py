M = {
    "ci3-killed": ("tests/ci_shards.py", 'NUMBER = re.compile(r"[1-9][0-9]{0,5}")', 'NUMBER = re.compile(r"[1-9][0-9]{0,6}")'),
    "ci3-survived": ("tests/ci_shards.py", "the median of file size", "the mean of file size"),
    "ci3-not-applied": ("tests/ci_shards.py", "this text is in no file of the repository", "any other text"),
}
KILL = {
    "ci3-killed": ("tests.test_ci_shards",),
    "ci3-survived": ("tests.test_ci_shards",),
    "ci3-not-applied": ("tests.test_ci_shards",),
}
