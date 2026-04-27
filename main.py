"""
反拖延监工 Agent - 5个阶段完整实现
=======================================
阶段一 PERCEPTION: 截图 -> AI分析
阶段二 MEMORY: 滑动窗口记忆
阶段三 EXPRESSION: 多样化语音吐槽
阶段四 ENFORCEMENT: 三振出局强制关闭
阶段五 DEPLOYMENT: 后台运行脚本
"""

import os
import sys
import time
import base64
import json
import subprocess
import random
from io import BytesIO
from datetime import datetime
from collections import deque
from typing import List, Optional
from dotenv import load_dotenv
from PIL import ImageGrab
import psutil
import win32gui
import win32process
import pyttsx3
from volcenginesdkarkruntime import Ark
from pydantic import BaseModel, Field

load_dotenv()

# ======================
# 全局配置
# ======================
WHITE_LIST = {
    "cmd.exe",
    "WindowsTerminal.exe",
    "OpenCode.exe",
    "opencode.exe",
    "Code.exe",
    "pycharm64.exe",
    "idea64.exe",
    "goland64.exe",
    "devenv.exe",
    "explorer.exe",
    "Taskmgr.exe",
    "python.exe",
    "node.exe",
    "java.exe",
    "notepad.exe",
    " subl",
    "sublime_text.exe",
}

VIDEO_KEYWORDS = [
    "bilibili",
    "b站",
    "youtube",
    "爱奇艺",
    "腾讯视频",
    "优酷",
    "直播",
    "game",
    "游戏",
    "抖音",
    "快手",
    "netflix",
    "spotify",
    "vlc",
]

memory_queue = deque(maxlen=int(os.getenv("MEMORY_WINDOW", 5)))
anger_count = 0
video_start_time = None
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 10))
VIDEO_THRESHOLD = int(os.getenv("VIDEO_THRESHOLD", 5))
START_DELAY = int(os.getenv("START_DELAY", 5))

# 语音引擎
tts_engine = pyttsx3.init()
tts_engine.setProperty("voice", os.getenv("VOICE_NAME", "Microsoft Huihui Desktop"))


# ======================
# 数据模型
# ======================
class MonitorResult(BaseModel):
    status: str = Field(description="working/slacking")
    summary: str = Field(description="画面描述")
    吐槽: str = Field(description="毒舌吐槽")
    warning: str = Field(description="mild/medium/severe/final")


# ======================
# 阶段一 PERCEPTION: 感知截图
# ======================
def get_foreground_info() -> tuple[str, str, list]:
    """获取前台应用、窗口标题、运行进程"""
    try:
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd) or ""
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process = psutil.Process(pid)
        app_name = process.name()
    except:
        return "Unknown", "", []

    # 获取运行进程
    running_apps = []
    for p in psutil.process_iter(["name"]):
        try:
            n = p.info.get("name")
            if n:
                running_apps.append(n.lower())
        except:
            pass

    return app_name, title, running_apps


def get_running_apps() -> list:
    """获取所有运行中的进程"""
    apps = []
    for p in psutil.process_iter(["name"]):
        try:
            n = p.info.get("name")
            if n:
                apps.append(n.lower())
        except:
            pass
    return apps


def check_background_video(running_apps: list) -> tuple[bool, str]:
    """检测后台是否有视频"""
    for kw in VIDEO_KEYWORDS:
        for app in running_apps:
            if kw in app:
                return True, kw
    return False, ""


def take_screenshot() -> str:
    """截图并转Base64"""
    img = ImageGrab.grab()
    img.thumbnail((1280, 720))
    buf = BytesIO()
    img.save(buf, format="PNG", quality=60)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


# ======================
# 阶段一: AI分析(Perception + 部分Memory)
# ======================
def analyze_screen(screenshot_b64: str, history: list) -> MonitorResult:
    """调用Doubao分析屏幕"""
    api_key = os.getenv("ARK_API_KEY", "")
    if not api_key or "your_" in api_key:
        return MonitorResult(
            status="working", summary="未配置API", 吐槽="", warning="mild"
        )

    # 构建历史(阶段二MEMORY)
    recent = list(history)[-3:]
    history_text = " | ".join([f"{h['status'][0]}" for h in recent]) if recent else "无"

    system_prompt = """你是美嘉毒舌监工。严格判断：
- 视频/直播/游戏=slacking
- 代码编辑器=working  
- 浏览器视频网站=slacking
返回JSON: {"status":"working/slacking","summary":"画面","吐槽":"毒舌","warning":"mild/medium/severe/final"}"""

    user_text = f"历史:{history_text}。判断:工作or摸鱼?"

    try:
        client = Ark(base_url=os.getenv("ARK_BASE_URL"), api_key=api_key)
        resp = client.responses.create(
            model=os.getenv("ARK_MODEL"),
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": user_text},
                        {"type": "input_image", "image_url": screenshot_b64},
                    ],
                },
            ],
        )

        text = resp.text
        if not text and resp.output:
            for item in resp.output:
                if hasattr(item, "content"):
                    for c in item.content:
                        if hasattr(c, "text") and c.text:
                            text = c.text
                            break

        if text:
            data = json.loads(text)
            return MonitorResult(
                status=data.get("status", "slacking"),
                summary=data.get("summary", ""),
                吐槽=data.get("吐槽", "喂！"),
                warning=data.get("warning", "medium"),
            )
    except Exception as e:
        print(f"API错误: {e}")

    return MonitorResult(
        status="slacking", summary="分析失败", 吐槽="嗯？", warning="medium"
    )


# ======================
# 阶段三 EXPRESSION: 语音输出
# ======================
SLACKING_TAUNTS = {
    "B站": [
        "B站有什么好看的？代码写完再看！",
        "又刷B站？KPL有代码香？",
        "B站弹幕再香也没代码香！",
        "B站刷不停，代码写不完！",
        "让你刷B站，，今晚加班！",
    ],
    "YouTube": [
        "YouTube？看什么看！",
        "油管视频那么好看？不如写代码！",
        "别刷油管了！干活！",
        "油管虽好，但不是工作时间！",
        "再看油管我就急！",
    ],
    "游戏": [
        "又在打游戏？代码写了？",
        "游戏重要还是KPI重要？",
        "打游戏的時候想一下你的工资！",
        "游戏那么好玩？不如写代码！",
        "打游戏时间够了吗！",
    ],
    "直播": [
        "直播那么好看？不如写代码！",
        "看直播能涨薪？",
        "主播分红给你？干活！",
        "直播虽好，但不能当饭吃！",
        "别看直播了，干活！",
    ],
    "短视频": [
        "抖音刷不停？工作做完了？",
        "短视频那么上瘾？代码写了吗！",
        "别刷了！干活！",
        "抖音刷多工资会涨？",
        "又刷抖音，良心不痛？",
    ],
    "音乐": [
        "听歌干活？一心二用？",
        "音乐这么好听的？不如写代码！",
        "干活时候别听歌！",
        "音乐党和工作不能兼得！",
        "听歌不如听我吐槽！",
    ],
    "default": [
        "喂！又摸鱼呢？",
        "还看？工作做完了？",
        "别看了！干活！",
        "再看下去今晚加班的就是你！",
        "摸鱼摸上瘾了？",
        "看什么看！干活！",
        "差不多得了！",
        "又在摸鱼，良心不会痛吗？",
        "别以为我没看到！",
        "好好干活不行吗！",
    ],
}

WORKING_TAUNTS = [
    "干得不错，继续保持！",
    "继续保持！",
    "很好！别骄傲！",
    "不错！再接再厉！",
]


def get_slacking_type(app_name: str, window_title: str, running_apps: list) -> str:
    """识别摸鱼类型"""
    title = window_title.lower()
    app = app_name.lower()

    # 终端/IDE 内容不算摸鱼
    if any(
        x in app
        for x in [
            "terminal",
            "powershell",
            "cmd",
            "code",
            "opencode",
            "pycharm",
            "idea",
        ]
    ):
        return ""

    # 浏览器检测
    if any(x in app for x in ["edge", "chrome", "brave", "firefox"]):
        if "bilibili" in title or "b站" in title:
            return "B站"
        elif "youtube" in title:
            return "YouTube"
        elif any(x in title for x in ["game", "游戏", "kpl", "赛事"]):
            return "游戏"
        elif "直播" in title:
            return "直播"
        elif any(x in title for x in ["抖音", "快手"]):
            return "短视频"
        return "浏览器"  # 不确定，但可能是工作相关

    # 其他应用
    if "spotify" in app:
        return "音乐"
    if "vlc" in app:
        return "视频"
    if "bilibili" in app:
        return "B站"

    return ""


def speak(text: str):
    """语音输出（非阻塞）"""
    try:
        # 停止当前语音
        tts_engine.stop()
        # 开始新语音
        tts_engine.say(text)

        # 后台运行（不阻塞）
        def run_async():
            try:
                tts_engine.runAndWait()
            except:
                pass

        import threading

        threading.Thread(target=run_async, daemon=True).start()
    except:
        print(f"🗣️ {text}")


def notify(title: str, content: str):
    """通知"""
    print(f"🔔 {title}: {content}")


# ======================
# 阶段四 ENFORCEMENT: 强制关闭
# ======================
def kill_app(process_name: str):
    """关闭应用"""
    try:
        subprocess.run(["taskkill", "/F", "/IM", process_name], capture_output=True)
        return True
    except:
        return False


def force_close_browsers():
    """强制关闭浏览器"""
    browsers = ["msedge.exe", "chrome.exe", "brave.exe", "firefox.exe"]
    for b in browsers:
        kill_app(b)


# ======================
# 主循环
# ======================
def main():
    global anger_count, video_start_time

    print(
        f"🚨 美嘉监工启动！检测间隔:{CHECK_INTERVAL}秒 | 视频阈值:{VIDEO_THRESHOLD}秒"
    )
    notify("美嘉已上线", "好好工作！")

    # 启动延迟
    print(f"⏳ {START_DELAY}秒后开始检测...")
    time.sleep(START_DELAY)

    while True:
        now = datetime.now().strftime("%H:%M:%S")

        # === PERCEPTION: 获取信息 ===
        app_name, window_title, running_apps = get_foreground_info()

        # 检测后台视频
        has_video, video_type = check_background_video(running_apps)

        # 快速判断
        app_lower = app_name.lower()
        is_whitelist = any(app_lower == x.lower() for x in WHITE_LIST)
        has_video_kw = any(kw in window_title.lower() for kw in VIDEO_KEYWORDS)

        # === AI分析 ===
        screenshot = take_screenshot()
        result = analyze_screen(screenshot, list(memory_queue))

        # 综合判断 - 白名单优先
        if is_whitelist:
            # 白名单应用直接判定为工作
            status = "working"
            slacking_type = ""
        elif has_video_kw:
            # 窗口有视频关键词
            status = "slacking"
            slacking_type = get_slacking_type(app_name, window_title, running_apps)
        else:
            # 让AI判断
            status = result.status
            slacking_type = (
                get_slacking_type(app_name, window_title, running_apps)
                if status == "slacking"
                else ""
            )

        # 更新记忆(阶段二MEMORY)
        memory_queue.append({"time": now, "status": status, "summary": result.summary})

        # === 处理 ===
        if status == "slacking":
            anger_count += 1

            # 多样化输出
            if slacking_type in SLACKING_TAUNTS:
                taunts = SLACKING_TAUNTS[slacking_type]
            else:
                taunts = SLACKING_TAUNTS["default"]
            taunt = random.choice(taunts)

            # 类型标签
            detail = f"[{slacking_type}]" if slacking_type else ""

            # 根据愤怒次数选择表情和文字警告
            if anger_count == 1:
                emoji = "😤"
                warn_text = "第1次警告"
            elif anger_count == 2:
                emoji = "😡"
                warn_text = "第2次警告"
            else:
                emoji = "🤬"
                warn_text = "第3次警告"

            print(f"{emoji} {now} {warn_text} {detail}{app_name}: {result.summary}")

            # 语音输出(阶段三EXPRESSION)
            speak(taunt)

            # 视频超时提醒
            if has_video or "edge" in app_name.lower():
                if not video_start_time:
                    video_start_time = time.time()
                elif time.time() - video_start_time > VIDEO_THRESHOLD:
                    speak(f"看了{VIDEO_THRESHOLD}秒了！还不干活？")
                    video_start_time = None
            else:
                video_start_time = None

            # === ENFORCEMENT: 三振出局 ===
            if anger_count == 1:
                speak("这是第1次！再摸下去别怪我不客气！")
            elif anger_count == 2:
                speak("第2次了！再不干活有你好看！")
            elif anger_count >= 3:
                speak("第3次了！关掉！别逼我动手！")
                time.sleep(1)
                force_close_browsers()
                print(f"🔴 {now} 强制关闭浏览器！")
                time.sleep(1)
                speak("已关闭！再摸鱼试试！")
                anger_count = 0  # 重置计数器
        else:
            anger_count = 0  # 工作时重置

            # 工作鼓励(偶尔)
            if random.random() < 0.2:
                speak(random.choice(WORKING_TAUNTS))

            print(f"✅ {now} 工作")

        time.sleep(CHECK_INTERVAL)


time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 美嘉监工已停止")
        print(f"统计: 检测次数={len(memory_queue)}, 摸鱼次数={anger_count}")
