# 演示数据包

本目录保存从当前 MySQL 数据库导出的演示数据，用于源码提交后的本地演示。

## 文件

- `demo_dataset.json`：当前已爬取数据的完整演示快照。

## 导出演示数据

在 `backend` 目录执行：

```powershell
..\venv\Scripts\python.exe scripts\export_demo_data.py
```

默认输出到：

```text
demo_data/demo_dataset.json
```

## 导入演示数据

在 `backend` 目录执行：

```powershell
..\venv\Scripts\python.exe scripts\import_demo_data.py --reset
```

`--reset` 会先清空系统演示相关数据表，再导入本数据包。若不希望清空已有数据，可以去掉 `--reset`。
