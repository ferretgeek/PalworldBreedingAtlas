# 安全策略 / Security policy

请通过 GitHub 的 **Security → Report a vulnerability** 私密报告安全问题。不要上传真实 `.sav`、玩家数据、本机路径、服务器地址、日志或诊断包。

Please report vulnerabilities privately through GitHub **Security → Report a vulnerability**. Do not upload real `.sav` files, player data, local paths, server addresses, logs, or diagnostics.

本项目把存档视为只读输入；任何写回、上传、遥测、远程更新或自动常驻扫描都属于安全边界变化，必须经过单独设计与审查。

存档在读取前检查文件大小，zlib 每一层按声明尺寸与全局预算有界解压；浏览器库存导入限制文件、记录和个体总量。服务器发布状态只保存稳定错误摘要，不持久化异常中的本机路径。

Saves are read-only inputs. Save writes, uploads, telemetry, remote updates, or continuous background scanning are security-boundary changes and require separate design and review.

Save size is checked before reading, every zlib layer has a declared and global output budget, and browser inventory import limits files and records. Server status persists only a stable error summary, never local paths from exception text.
