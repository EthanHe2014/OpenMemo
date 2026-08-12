#!/usr/bin/env python3
"""看护（watchdog）测试脚本 —— 一键制造三类问题并验证检测

用法:
    python scripts/test_watchdog.py
    或
    .venv/bin/python scripts/test_watchdog.py

它会:
1. 伪造一条「AI 承诺了但没建任务」的对话记录
2. 用 API 建一个「时间在过去」的任务
3. 用 API 建两个「同内容同时间」的重复任务
4. 运行 watchdog 检查 → 应该报出 3 个问题
5. 清理测试数据（不留垃圾）
"""
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:18890"
DB = Path(__file__).resolve().parent.parent / "data" / "openmemo.db"

# 先加路径，保证能 import openmemo.watchdog
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def seed_promise_violation():
    """伪造：用户要提醒 + AI 说已记下，但没建任务"""
    conn = sqlite3.connect(str(DB))
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute(
        "INSERT INTO conversations (session_id, role, content, created_at) VALUES (?,?,?,?)",
        ("watchdog_test", "user", "5分钟后提醒我喝水", now),
    )
    cur.execute(
        "INSERT INTO conversations (session_id, role, content, created_at) VALUES (?,?,?,?)",
        ("watchdog_test", "assistant", "好的，已记下，5分钟后提醒你喝水", now),
    )
    conn.commit()
    conn.close()
    print("  ① 伪造承诺未落地：对话『5分钟后提醒我喝水』→『好的，已记下』（无任务）")


def seed_past_time_task():
    """用 API 建一个过去时间的任务（绕过 AI，直接造）"""
    past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    r = httpx.post(
        f"{BASE}/api/tasks",
        json={"content": "看护测试-过期时间", "trigger_time": past, "priority": "medium"},
        timeout=10,
        trust_env=False,
    ).json()
    print(f"  ② 创建过去时间任务 #{r['task']['task_id']} @ {past}")
    return r["task"]["task_id"]


def seed_duplicates():
    """用 API 建两个同内容同时间任务"""
    future = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    ids = []
    for _ in range(2):
        r = httpx.post(
            f"{BASE}/api/tasks",
            json={"content": "看护测试-重复", "trigger_time": future, "priority": "medium"},
            timeout=10,
            trust_env=False,
        ).json()
        ids.append(r["task"]["task_id"])
    print(f"  ③ 创建重复任务 #{ids[0]} #{ids[1]} @ {future}")
    return ids


def cleanup(task_ids):
    conn = sqlite3.connect(str(DB))
    cur = conn.cursor()
    cur.execute("DELETE FROM conversations WHERE session_id='watchdog_test'")
    print("  - 清理伪造对话")
    for tid in task_ids:
        cur.execute("DELETE FROM tasks WHERE task_id=?", (tid,))
        print(f"  - 清理任务 #{tid}")
    conn.commit()
    conn.close()


def main():
    print("=" * 56)
    print("  Watchdog 测试：制造问题 → 运行检测 → 验证 → 清理")
    print("=" * 56)
    print("准备测试数据...")
    ids = []
    seed_promise_violation()
    ids.append(seed_past_time_task())
    ids.extend(seed_duplicates())
    time.sleep(1)

    print("\n运行检测（python -m openmemo.watchdog --once）...")
    from openmemo.watchdog import run_watchdog

    problems = run_watchdog(hours=24)
    print(f"\n检测结果：发现 {len(problems)} 个问题")
    for p in problems:
        print("  ⚠️", p)

    # 判定
    ok = all(
        any(k in p for p in problems)
        for k in ("承诺未落地", "过期时间", "疑似重复")
    )
    print("\n" + ("✅ 三类问题全部被检测到，测试通过！" if ok else "❌ 有检测项未命中，请检查"))

    print("\n清理测试数据...")
    cleanup(ids)
    print("✅ 清理完成")


if __name__ == "__main__":
    main()
