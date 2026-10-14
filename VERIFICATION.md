# 验证记录

验证日期：2026-10-14。环境：Windows 10、Python 3.14.5、PySide6 6.12.0、FFmpeg 8.1.1。

## 检查范围

- 后端：裁剪、全部 9 种曲线的真实 FFmpeg 输出采样、默认恒功率正弦配对、对数/指数逆函数关系、重叠淡化、多声道、8 种导出格式、位深、metadata、封面、章节、失败保护及后台取消。
- 界面：打开自动播放、固定预览布局、单图标模式切换、裁剪/淡化手柄、右键菜单、时长同步、重置、试听和保存；曲线端点、手柄连接点及走带线边缘几何校验。
- 打包：EXE 从命令行打开临时静音 WAV，创建窗口并正常关闭。

## 重现检查

先按 README 配置依赖，在项目目录运行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tests\check_package.py
# 可选：使用自己的音频检查原生界面（静音，不修改源文件）
.\.venv\Scripts\python.exe tests\capture_desktop.py "C:\Audio\sample.wav"
```

打包检查需要先生成 `dist/AudioCut/AudioCut.exe`。测试使用临时合成音频；日志、截图和二进制生成物只保留在本地，不纳入源码仓库。

## 检查边界

播放检查使用静音，验证解码、播放状态和时钟，未主观试听扬声器或耳机输出。曲线名称参考 Wwise 官方英文术语，采用本工具的归一化函数，未与 Wwise 内部插值逐采样比对。尚未在其他 Windows 电脑上验证。格式和 metadata 的兼容范围见 README。
