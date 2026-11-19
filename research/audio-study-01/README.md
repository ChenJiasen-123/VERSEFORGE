# 朗读研究01：同词同标点，不同停顿安排

2026-11-18。已实际生成三段中文合成语音，文字来自本项目原创材料，汉字与标点保持一致：

> 我把你留下的杯子放回窗边，天色暗了。

音频使用本机已安装的Microsoft Huihui Desktop，速度设置0、音量100，无配乐。没有调用外部语音服务、真实机器人或模型API，也没有改变Agent。合成调用参考Microsoft Learn的[SpeakSsml](https://learn.microsoft.com/en-us/dotnet/api/system.speech.synthesis.speechsynthesizer.speakssml?view=netframework-4.8.1)与[SetOutputToWaveFile](https://learn.microsoft.com/en-us/dotnet/api/system.speech.synthesis.speechsynthesizer.setoutputtowavefile?view=netframework-4.8.1)。

## 三段材料

- [连续读法](continuous.wav)：不显式插入停顿，原逗号保留，仍可能有引擎自然停顿。
- [悬置处停顿](suspended.wav)：在“留下的”与“放回”之后各请求400毫秒停顿。
- [语义组后停顿](phrased.wav)：在“杯子”与“窗边，”之后各请求400毫秒停顿。

SSML源文件一并保存，参数和实际WAV时长等信息见`manifest.json`。请求的400毫秒不等于已实测语流中恰有400毫秒静音；语音引擎也可能调整邻近声音，所以不能用总时长相减直接解释每次停顿。

## 已验证什么

已核三份SSML的汉字与标点相同，音频均可由Python的WAV读取器打开，且包含非零PCM信号。保存采样参数、时长与哈希便于追踪。以上是文件和输入完整性检查，不证明发音准确或听感优美。

## 尚未做什么

新增[信号核查记录](signal-observations.md)：低能量区间检测表明实际间隔与时长并非简单等于SSML请求值，语义组版还存在显式停顿与逗号组合的影响。当前材料不视为完全隔离停顿位置效应的实验，不能据参数相同就宣布条件已完全相等。

尚无真实听者偏好、独立盲评、助手实际听辨或机器人播放。文件名揭示处理方式，作者也知道预期，故当前不是盲评材料。两段显式停顿的版本只有请求停顿量相同，实际时长并不强行拉齐。

## 听辨时只回答三个具体问题

1. 哪一处更容易理解，哪一处有不必要的等待？请指出具体词语。
2. 停顿是否改变“留下的杯子”的感受？它让关系更清楚，还是只显得刻意？
3. 哪一种更适合这段文字的处境？允许平局、不喜欢所有版本或判断不了。

不要先按标题判断哪段更好。若以后正式测试，应另行匿名编号并交换顺序，保留原文件和对应关系。这次不自动生成偏好标签，不将合成语音存在当作音韵目标达成。
