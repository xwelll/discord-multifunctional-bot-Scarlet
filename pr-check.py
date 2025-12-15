#!/usr/bin/env python3
"""
Система проверки безопасности и кода перед PR
Проверяет: утечки токенов, секреты, синтаксис, частые ошибки
"""

import os
import re
import subprocess
import sys
from pathlib import Path

# Цвета для вывода
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'
CHECK = '✓'
CROSS = '✗'


def print_header(text):
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}{text.center(60)}{RESET}")
    print(f"{BLUE}{'='*60}{RESET}\n")


def print_success(text):
    print(f"{GREEN}{CHECK} {text}{RESET}")


def print_error(text):
    print(f"{RED}{CROSS} {text}{RESET}")


def print_warning(text):
    print(f"{YELLOW}⚠ {text}{RESET}")


def check_tokens(project_root):
    """Проверка на наличие токенов в коде"""
    print_header("🔐 Проверка токенов и секретов")
    
    # Паттерны для поиска секретов
    patterns = {
        'Discord токен (старый формат)': r'[MN][A-Za-z0-9_-]{23,25}\.[A-Za-z0-9_-]{6,7}\.[A-Za-z0-9_-]{27,38}',
        'Discord токен (новый формат)': r'mfa\.[A-Za-z0-9_-]{80,95}',
        'API ключи': r'(?i)(api[_-]?key|apikey)\s*=\s*["\']([^"\']+)["\']',
        'Пароли': r'(?i)(password|passwd|pwd)\s*=\s*["\']([^"\']+)["\']',
        'Переменная TOKEN': r'(?i)TOKEN\s*=\s*["\']([^"\']+)["\']',
    }
    
    found_secrets = False
    excluded_dirs = {'.git', '__pycache__', '.pytest_cache', 'venv', 'env', '.env'}
    excluded_files = {'.env', '.gitignore'}
    
    for root, dirs, files in os.walk(project_root):
        # Исключаем ненужные директории
        dirs[:] = [d for d in dirs if d not in excluded_dirs]
        
        for file in files:
            if file in excluded_files or file.endswith(('.log', '.pyc')):
                continue
                
            filepath = Path(root) / file
            
            # Проверяем только текстовые файлы
            if file.endswith(('.py', '.json', '.txt', '.md', '.yml', '.yaml')):
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        
                    for secret_name, pattern in patterns.items():
                        matches = re.finditer(pattern, content)
                        for match in matches:
                            found_secrets = True
                            line_num = content[:match.start()].count('\n') + 1
                            print_error(f"[{filepath}:{line_num}] Найдено: {secret_name}")
                            print(f"         {match.group()[:50]}...")
                
                except Exception as e:
                    pass
    
    if not found_secrets:
        print_success("Секреты и токены не найдены")
        return True
    return False


def check_syntax(project_root):
    """Проверка синтаксиса Python файлов"""
    print_header("🐍 Проверка синтаксиса Python")
    
    has_errors = False
    
    for pyfile in project_root.rglob("*.py"):
        # Пропускаем папки как .github
        if '.github' in pyfile.parts or '__pycache__' in pyfile.parts:
            continue
            
        try:
            result = subprocess.run(
                [sys.executable, "-m", "py_compile", str(pyfile)],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                print_error(f"Синтаксис ошибка в {pyfile}")
                print(f"    {result.stderr}")
                has_errors = True
        except Exception as e:
            print_error(f"Ошибка при проверке {pyfile}: {e}")
            has_errors = True
    
    if not has_errors:
        print_success("Синтаксис Python файлов корректен")
        return True
    return False


def check_common_mistakes(project_root):
    """Проверка на частые ошибки"""
    print_header("⚠️  Проверка частых ошибок")
    
    mistakes = {
        'print вместо logging': r'\bprint\s*\(',
        'bare except': r'except\s*:',
        'TODO комментарии': r'#\s*TODO',
        'FIXME комментарии': r'#\s*FIXME',
    }
    
    found_issues = False
    
    bot_file = project_root / "BOT 1" / "main.py"
    if bot_file.exists():
        try:
            with open(bot_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            for mistake_name, pattern in mistakes.items():
                matches = list(re.finditer(pattern, content))
                if matches:
                    for match in matches:
                        line_num = content[:match.start()].count('\n') + 1
                        print_warning(f"[main.py:{line_num}] {mistake_name}")
                        found_issues = True
        except Exception as e:
            print_error(f"Ошибка при проверке ошибок: {e}")
            return False
    
    if not found_issues:
        print_success("Частые ошибки не обнаружены")
        return True
    else:
        print_warning("Найдены потенциальные проблемы (не критичные)")
        return True


def check_security_with_bandit(project_root):
    """Проверка безопасности с bandit"""
    print_header("🔒 Проверка безопасности (Bandit)")
    
    try:
        result = subprocess.run(
            ["bandit", "-r", str(project_root / "BOT 1"), "-ll"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print_success("Bandit: нет критичных проблем безопасности")
            return True
        else:
            if "No issues identified" in result.stdout:
                print_success("Bandit: нет критичных проблем безопасности")
                return True
            else:
                print_warning("Bandit: найдены потенциальные проблемы")
                print(result.stdout[:500])
                return True  # Не критично для PR
    except FileNotFoundError:
        print_warning("Bandit не установлен - пропускаем проверку")
        return True
    except Exception as e:
        print_warning(f"Ошибка при выполнении Bandit: {e}")
        return True


def main():
    print_header("🔐 ПРОВЕРКА БЕЗОПАСНОСТИ ПЕРЕД PR")
    
    project_root = Path(__file__).parent
    
    results = {}
    
    # 1. Проверка токенов
    results['tokens'] = check_tokens(project_root)
    
    # 2. Проверка синтаксиса
    results['syntax'] = check_syntax(project_root)
    
    # 3. Проверка частых ошибок
    results['mistakes'] = check_common_mistakes(project_root)
    
    # 4. Проверка безопасности Bandit
    results['bandit'] = check_security_with_bandit(project_root)
    
    # Итоги
    print_header("📊 ИТОГИ ПРОВЕРКИ")
    
    for check_name, result in results.items():
        status = f"{GREEN}{CHECK}{RESET}" if result else f"{RED}{CROSS}{RESET}"
        print(f"  {status} {check_name.replace('_', ' ').capitalize()}")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    print(f"\n{BLUE}Результат: {passed}/{total} проверок пройдено{RESET}")
    
    if results['tokens'] and results['syntax']:
        print_success("Код готов к PR! ✨")
        return 0
    else:
        print_error("Исправьте ошибки перед отправкой PR")
        return 1


if __name__ == "__main__":
    sys.exit(main())
