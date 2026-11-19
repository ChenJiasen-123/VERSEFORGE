from html import escape


def speech_ssml(poem, line_pause_ms=350):
    """Export only; organizer support for SSML is not assumed."""
    if type(line_pause_ms) is not int or not 0 <= line_pause_ms <= 2000:
        raise ValueError('行间停顿须为0—2000毫秒整数')
    separator = f'<break time="{line_pause_ms}ms"/>' if line_pause_ms else ''
    body = separator.join(escape(line) for line in poem['lines'])
    return '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">' + body + '</speak>'


def speech_text(poem):
    return poem["title"] + "。\n" + "\n".join(poem["lines"])


def speak_mock(poem):
    """No audio or network calls. Replace only after receiving organizer docs."""
    print("\n[模拟朗诵：仅打印文本，没有连接机器人或播放声音]")
    print(speech_text(poem))
