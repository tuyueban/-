# 音乐热度分析后端

后端采用 FastAPI + SQLAlchemy 分层结构，数据存储在 MySQL Workbench 8.0 CE 对应的 MySQL 数据库中。系统定位为：基于网易云音乐、QQ音乐、酷狗音乐三大音乐平台公开榜单数据的音乐热度分析系统。

## 采集范围

- 网易云音乐：热歌榜、新歌榜、飙升榜、原创榜
- QQ音乐：热歌榜、新歌榜、飙升榜、流行指数榜
- 酷狗音乐：TOP500、新歌榜、飙升榜

系统只处理三大音乐平台公开榜单和公开统计指标，不扩展到三大平台以外的辅助平台，也不做非榜单内容分析。

## 关键接口

- `GET /health`：健康检查
- `GET /api/charts/dashboard`：首页汇总数据
- `GET /api/charts/daily-hot`：歌曲热度日榜
- `GET /api/charts/weekly-hot`：歌曲热度周榜
- `GET /api/charts/rising`：飙升榜
- `GET /api/charts/new-songs`：三平台合并新歌榜
- `GET /api/charts/interaction-heat`：互动热度榜
- `GET /api/charts/platform`：平台原始榜单
- `GET /api/songs/search`：歌曲搜索
- `GET /api/songs/{song_id}`：歌曲详情
- `GET /api/artists/rank`：热门歌手榜
- `GET /api/artists/{artist_name}`：歌手详情
- `POST /api/crawler/run`：采集歌曲榜单和指标
- `POST /api/crawler/run-artists`：采集平台歌手榜

## 热度计算口径

歌曲三平台综合热度只使用主热歌榜：

- 网易云音乐热歌榜
- QQ音乐热歌榜
- 酷狗音乐 TOP500

平台热度分采用动态权重。互动指标缺失时不会按 0 直接扣分，而是根据可用字段重新分配权重。指标先做 `log1p(value)`，再在同平台、同日期、同指标内部做 0-100 归一化。

最终歌曲热度分：

```text
final_heat_score = available_platform_avg_score * 0.75 + cross_platform_score * 0.25
```

## 歌手榜口径

歌手榜基于三大音乐平台公开歌手榜单或歌手推荐列表数据进行综合评分，不通过歌曲热度反推歌手排名。由于不同平台歌手维度数据公开程度不同，歌手榜属于参考型榜单，不等同于平台官方艺人榜。

```text
歌手热度分 =
最佳平台歌手榜排名分 * 0.40
+ 平均平台歌手榜排名分 * 0.40
+ 平台覆盖分 * 0.20
```

## 版本合并

不同版本歌曲合并到同一标准歌曲下，同时在 `PlatformSong` 保留：

- `raw_song_name`
- `raw_artist_name`
- `version_type`

伴奏、Karaoke、Instrumental 版本不贡献歌曲热度分。

## 字段级采集成功率

爬虫结果分别统计：

- `play_count_success_count`
- `favorite_count_success_count`
- `comment_count_success_count`
- `play_count_success_rate`
- `favorite_count_success_rate`
- `comment_count_success_rate`

## 运行脚本

```powershell
python scripts\run_crawler.py --platform all
python scripts\run_crawler.py --platform all --artists-only
python scripts\run_heat_score.py --date 2026-06-29
python scripts\run_ai_analysis.py --date 2026-06-29 --limit 20
```

`--limit` 仅用于测试，不建议用于演示或正式数据生成。
