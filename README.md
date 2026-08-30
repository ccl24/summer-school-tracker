# Ivy Summer Tracker

面向高中生的常春藤大学夏校申请日期追踪器。网页只展示大学官方页面中的公开信息；申请前请始终以官方页面为准。

## 本地预览

```powershell
python -m http.server 8000
```

然后打开 `http://localhost:8000`。采集器需要 Python 3.11+：

```powershell
python -m pip install -r requirements.txt
python scripts/collector.py
python -m unittest discover -s tests -v
```

## 维护原则

- `data/sources.json` 是唯一的官方来源白名单；每个来源最多每日请求一次。
- 解析异常不会覆盖已验证日期；异常会写入 `data/review_issues.json`，GitHub Actions 再创建或关闭对应 Issue。
- 所有日期保留原始时区和官方原文。滚动录取、TBA 和页面仅显示 Closed 时不会臆造具体日期。

GitHub Pages 部署由 `.github/workflows/update-and-deploy.yml` 处理。仓库需在 Settings → Pages 中选择 **GitHub Actions** 作为发布来源。

