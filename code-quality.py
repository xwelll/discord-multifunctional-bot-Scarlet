#!/usr/bin/env python3
"""
Система проверки качества кода
Проверяет: синтаксис, форматирование, стиль, импорты
"""

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


def run_check(name, command):
    """Запускает проверку и возвращает результат"""
    print(f"\n{BLUE}→ Проверка: {name}...{RESET}")
    try:
        result = subprocess.run(command, capture_output=True, text=True, shell=True)
        if result.returncode == 0:
            print_success(f"{name} прошла успешно")
            return True
        else:
            print_error(f"{name} не прошла!")
            if result.stdout:
                print(f"  {result.stdout}")
            if result.stderr:
                print(f"  {result.stderr}")
            return False
    except Exception as e:
        print_error(f"Ошибка при выполнении {name}: {e}")
        return False


def main():
    print_header("🔍 ПРОВЕРКА КАЧЕСТВА КОДА")
    
    project_root = Path(__file__).parent
    bot_file = project_root / "BOT 1" / "main.py"
    
    if not bot_file.exists():
        print_error(f"Файл {bot_file} не найден!")
        sys.exit(1)
    
    results = {}
    
    # 1. Проверка синтаксиса
    print_header("Синтаксис Python")
    results['syntax'] = run_check(
        "Синтаксис",
        f'python -m py_compile "{bot_file}"'
    )
    
    # 2. Проверка черезformat (black)
    print_header("Форматирование кода")
    results['black'] = run_check(
        "Black (форматирование)",
        f'black --check "{bot_file}"'
    )
    
    # 3. Проверка импортов (isort)
    print_header("Сортировка импортов")
    results['isort'] = run_check(
        "isort (импорты)",
        f'isort --check-only "{bot_file}"'
    )
    
    # 4. Проверка стиля (flake8)
    print_header("Стиль кода (PEP 8)")
    results['flake8'] = run_check(
        "flake8 (стиль)",
        f'flake8 "{bot_file}" --max-line-length=100 --extend-ignore=E203,W503'
    )
    
    # 5. Проверка качества (pylint)
    print_header("Анализ качества кода")
    results['pylint'] = run_check(
        "Pylint (качество)",
        f'pylint "{bot_file}" --disable=C0111,C0103,R0913 --max-line-length=100'
    )
    
    # Итоги
    print_header("📊 ИТОГИ")
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for check_name, result in results.items():
        status = f"{GREEN}{CHECK}{RESET}" if result else f"{RED}{CROSS}{RESET}"
        print(f"  {status} {check_name.capitalize()}")
    
    print(f"\n{BLUE}Результат: {passed}/{total} проверок пройдено{RESET}")
    
    if passed == total:
        print_success("Все проверки пройдены! ✨")
        return 0
    else:
        print_error(f"Не пройдено {total - passed} проверок")
        return 1


if __name__ == "__main__":
    sys.exit(main())
