"""
数据库更新脚本
用于执行数据库更新，添加内容生成和MCP服务管理相关的表
"""

import os
import sys
from pathlib import Path
import pymysql
from pymysql import Error
from dotenv import load_dotenv

# 动态查找项目根目录并添加到Python路径
# 注意：这里不能导入backend模块，因为还没有添加到sys.path
current_file = Path(__file__).resolve()
project_root = current_file
max_depth = 10
depth = 0

# 向上查找项目根目录
while depth < max_depth:
    parent = project_root.parent
    if parent == project_root:
        break
    # 检查是否存在特征文件/目录
    if (parent / ".env").exists() or (parent / "backend").exists():
        project_root = parent
        break
    project_root = parent
    depth += 1

sys.path.insert(0, str(project_root))

# 加载环境变量
load_dotenv()


def get_db_config():
    """获取数据库配置"""
    return {
        'host': os.getenv('MYSQL_HOST', 'localhost'),
        'port': int(os.getenv('MYSQL_PORT', 3306)),
        'user': os.getenv('MYSQL_USERNAME', 'root'),
        'password': os.getenv('MYSQL_PASSWORD', ''),
        'database': os.getenv('MYSQL_DATABASE', 'personal_agent'),
        'charset': 'utf8mb4'
    }


def read_sql_file(file_path):
    """读取SQL文件"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f"错误：找不到文件 {file_path}")
        return None
    except Exception as e:
        print(f"错误：读取文件失败 - {str(e)}")
        return None


def execute_sql_script(cursor, sql_script):
    """执行SQL脚本"""
    # 分割SQL语句（处理DELIMITER）
    statements = []
    current_statement = []
    delimiter = ';'
    in_delimiter_block = False

    for line in sql_script.split('\n'):
        line = line.strip()

        # 跳过注释和空行
        if not line or line.startswith('--'):
            continue

        # 处理DELIMITER命令
        if line.upper().startswith('DELIMITER'):
            if '$$' in line:
                delimiter = '$$'
                in_delimiter_block = True
            else:
                delimiter = ';'
                in_delimiter_block = False
            continue

        current_statement.append(line)

        # 检查是否到达语句结束
        if line.endswith(delimiter):
            statement = ' '.join(current_statement)
            # 移除结束符
            statement = statement[:-len(delimiter)].strip()
            if statement:
                statements.append(statement)
            current_statement = []

    # 执行所有语句
    success_count = 0
    error_count = 0

    for i, statement in enumerate(statements, 1):
        try:
            # 跳过SET命令（某些可能不被支持）
            if statement.upper().startswith('SET FOREIGN_KEY_CHECKS'):
                cursor.execute(statement)
                continue

            cursor.execute(statement)
            success_count += 1

            # 显示进度
            if i % 5 == 0:
                print(f"已执行 {i}/{len(statements)} 条语句...")

        except Error as e:
            error_count += 1
            # 忽略"表已存在"和"触发器已存在"的错误
            if 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
                print(f"跳过：{statement[:50]}... (已存在)")
            else:
                print(f"错误：执行失败 - {str(e)}")
                print(f"SQL: {statement[:100]}...")

    return success_count, error_count


def backup_database(config):
    """备份数据库（可选）"""
    try:
        import subprocess
        from datetime import datetime

        backup_dir = Path(__file__).parent / 'backups'
        backup_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = backup_dir / f"backup_{timestamp}.sql"

        cmd = [
            'mysqldump',
            '-h', config['host'],
            '-P', str(config['port']),
            '-u', config['user'],
            f"-p{config['password']}",
            config['database']
        ]

        print(f"正在备份数据库到 {backup_file}...")
        with open(backup_file, 'w', encoding='utf-8') as f:
            subprocess.run(cmd, stdout=f, check=True)

        print(f"✓ 备份完成：{backup_file}")
        return True

    except Exception as e:
        print(f"警告：备份失败 - {str(e)}")
        print("继续执行更新...")
        return False


def check_tables_exist(cursor):
    """检查基础表是否存在"""
    cursor.execute("SHOW TABLES LIKE 'users'")
    if not cursor.fetchone():
        print("错误：基础表不存在，请先执行 create_tables.sql")
        return False
    return True


def verify_update(cursor):
    """验证更新结果"""
    print("\n验证更新结果...")

    # 检查内容生成相关表
    content_tables = ['content_generations', 'content_projects', 'content_chapters', 'content_characters']
    print("\n内容生成相关表:")
    for table in content_tables:
        cursor.execute(f"SHOW TABLES LIKE '{table}'")
        if cursor.fetchone():
            print(f"  ✓ {table}")
        else:
            print(f"  ✗ {table} (未创建)")

    # 检查MCP相关表
    mcp_tables = ['mcp_services', 'mcp_call_logs', 'mcp_user_configs', 'mcp_usage_stats']
    print("\nMCP服务管理表:")
    for table in mcp_tables:
        cursor.execute(f"SHOW TABLES LIKE '{table}'")
        if cursor.fetchone():
            print(f"  ✓ {table}")
        else:
            print(f"  ✗ {table} (未创建)")

    # 检查MCP默认配置
    cursor.execute("SELECT COUNT(*) as count FROM mcp_services")
    result = cursor.fetchone()
    if result:
        count = result[0]
        print(f"\nMCP默认服务配置: {count} 个")
        if count > 0:
            cursor.execute("SELECT name, is_enabled FROM mcp_services")
            for row in cursor.fetchall():
                status = "启用" if row[1] else "禁用"
                print(f"  - {row[0]} ({status})")


def main():
    """主函数"""
    print("=" * 60)
    print("数据库更新脚本")
    print("=" * 60)

    # 获取数据库配置
    config = get_db_config()
    print(f"\n数据库配置:")
    print(f"  主机: {config['host']}:{config['port']}")
    print(f"  用户: {config['user']}")
    print(f"  数据库: {config['database']}")

    # 确认执行
    print("\n此脚本将添加以下表到数据库:")
    print("  - 内容生成相关表 (4个)")
    print("  - MCP服务管理表 (4个)")

    response = input("\n是否继续？(y/n): ").strip().lower()
    if response != 'y':
        print("已取消更新")
        return

    # 询问是否备份
    response = input("是否先备份数据库？(y/n): ").strip().lower()
    if response == 'y':
        backup_database(config)

    connection = None
    cursor = None

    try:
        # 连接数据库
        print("\n正在连接数据库...")
        connection = pymysql.connect(**config)
        cursor = connection.cursor()
        print("✓ 数据库连接成功")

        # 检查基础表
        if not check_tables_exist(cursor):
            return

        # 读取SQL文件
        sql_file = Path(__file__).parent / 'update_database.sql'
        print(f"\n正在读取SQL文件: {sql_file}")
        sql_script = read_sql_file(sql_file)

        if not sql_script:
            return

        print("✓ SQL文件读取成功")

        # 执行SQL脚本
        print("\n开始执行SQL脚本...")
        success_count, error_count = execute_sql_script(cursor, sql_script)

        # 提交事务
        connection.commit()

        print(f"\n执行完成:")
        print(f"  成功: {success_count} 条")
        print(f"  失败: {error_count} 条")

        # 验证更新
        verify_update(cursor)

        print("\n" + "=" * 60)
        print("数据库更新完成！")
        print("=" * 60)

    except Error as e:
        print(f"\n错误：数据库操作失败 - {str(e)}")
        if connection:
            connection.rollback()
        sys.exit(1)

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
            print("\n数据库连接已关闭")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n用户中断执行")
        sys.exit(0)
    except Exception as e:
        print(f"\n未预期的错误: {str(e)}")
        sys.exit(1)
