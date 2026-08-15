"""OpenMemo 命令行入口"""
import sys
import asyncio
from .server import run_server
from .tasks import TaskManager, init_db
from .voice import speak, speak_sync
from .conversation import process_message


def main():
    """Main CLI entry point"""
    if len(sys.argv) < 2:
        print("OpenMemo - AI-powered personal voice assistant")
        print()
        print("Usage:")
        print("  openmemo server          Start the server")
        print("  openmemo chat            Interactive chat mode")
        print("  openmemo speak <text>    Speak text aloud")
        print("  openmemo tasks           List pending tasks")
        print("  openmemo init            Initialize database")
        print("  openmemo config          Show all settings")
        print("  openmemo config get <key>    Show one setting")
        print("  openmemo config set <key> <value>  Change a setting")
        print("  openmemo config reset <key>    Revert to .env default")
        print()
        print("Settings keys: ai_model, ai_base_url, ai_api_key, search_provider,")
        print("               search_api_key, search_base_url, tts_voice")
        return
    
    command = sys.argv[1]
    
    if command == "server":
        print("Starting OpenMemo server...")
        run_server()
    
    elif command == "chat":
        init_db()
        print("OpenMemo Chat Mode (type 'quit' to exit)")
        print("-" * 40)
        
        while True:
            try:
                user_input = input("You: ").strip()
                if user_input.lower() in ['quit', 'exit', 'q']:
                    print("Goodbye!")
                    break
                if not user_input:
                    continue
                
                reply = asyncio.run(process_message("cli_user", user_input, speak_response=True))
                print(f"OpenMemo: {reply}")
            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye!")
                break
    
    elif command == "speak":
        if len(sys.argv) < 3:
            print("Usage: openmemo speak <text>")
            return
        text = " ".join(sys.argv[2:])
        print(f"Speaking: {text}")
        asyncio.run(speak(text))
    
    elif command == "tasks":
        init_db()
        tm = TaskManager()
        tasks = tm.list_tasks(status="pending")
        if not tasks:
            print("No pending tasks.")
            return
        
        print("Pending Tasks:")
        print("-" * 40)
        for task in tasks:
            time_info = f" @ {task['trigger_time']}" if task['trigger_time'] else ""
            priority = f" [{task['priority']}]" if task['priority'] != 'medium' else ""
            print(f"  {task['task_id']}. {task['content']}{time_info}{priority}")
    
    elif command == "init":
        init_db()
        print("Database initialized.")

    elif command == "config":
        handle_config(sys.argv[2:])

    else:
        print(f"Unknown command: {command}")
        print("Run 'openmemo' for help.")


def handle_config(args: list):
    """openmemo config [get <key> | set <key> <value> | reset <key>]"""
    from .config import CONFIG_KEYS, get_setting, set_setting, get_all_settings, mask_secret

    if not args:
        # 列出全部
        all_settings = get_all_settings()
        print("OpenMemo 配置：")
        print("-" * 60)
        for key, info in all_settings.items():
            val = info["value"]
            ro = "（只读）" if info.get("readonly") else ""
            print(f"  {key:<16} {val if val else '（未设置，用 .env/默认）'} {ro}")
            print(f"      ↳ {info['description']}")
        return

    sub = args[0]
    if sub == "get" and len(args) >= 2:
        key = args[1]
        if key not in CONFIG_KEYS:
            print(f"未知配置项: {key}。可用: {', '.join(CONFIG_KEYS)}")
            return
        val = get_setting(key)
        if CONFIG_KEYS[key][3] and val:  # 敏感
            print(f"{key} = {mask_secret(str(val))}")
        else:
            print(f"{key} = {val if val else '（未设置）'}")

    elif sub == "set" and len(args) >= 3:
        key, value = args[1], args[2]
        if key not in CONFIG_KEYS:
            print(f"未知配置项: {key}。可用: {', '.join(CONFIG_KEYS)}")
            return
        if set_setting(key, value):
            print(f"✅ {key} = {value}（已保存到 settings.json，立即生效）")
        else:
            print(f"设置失败: {key}")

    elif sub == "reset" and len(args) >= 2:
        key = args[1]
        if key not in CONFIG_KEYS:
            print(f"未知配置项: {key}")
            return
        set_setting(key, None)
        print(f"↩️  {key} 已回退到 .env 默认值")

    else:
        print("用法: openmemo config [get <key> | set <key> <value> | reset <key>]")


if __name__ == "__main__":
    main()
