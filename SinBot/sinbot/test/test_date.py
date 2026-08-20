import dateparser

import jionlp

test_strings = [
    "明天晚上八点",
    "明天 晚上 八点", # 尝试加入空格
    "明晚八点",       # 尝试更口语化的表达
    "1 hour ago"
]

for s in test_strings:
    # 尝试不同的语言代码组合
    for lang in [['zh'], ['zh', 'zh-Hant'], None]:
        try:
            result = dateparser.parse(s, languages=lang)
            if result:
                print(f"成功: '{s}' -> {result} (使用语言: {lang})")
                break
            result = jionlp.parse_time(s)
            if result:
                print(f"成功: '{s}' -> {result} (使用语言: {lang},使用jionpl)")
                break
        except Exception as e:
            print(f"解析 '{s}' 时出错: {e}")
    else:
        print(f"失败: 无法解析 '{s}'")