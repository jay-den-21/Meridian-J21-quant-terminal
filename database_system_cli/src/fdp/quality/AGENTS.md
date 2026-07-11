# Data Quality Context

本文件适用于 `fdp.quality`，并继承上级 `AGENTS.md`。

## 本层拥有

- duplicate、missing trading day、OHLCV、calendar alignment 等检测 query。
- validation run 编排，以及 `data_quality_check_run`/`data_quality_issue` 记录。

## 本层不拥有

- 自动补值、删除价格行、调用 provider 或执行 repair/quarantine。
- 将“没有被加载的全市场 instrument”自动视为 missing issue。

## 开工前读取

- `../../../PROJECT.md` 的 Validate quality 章节
- `../storage/AGENTS.md`
- `validation.py` 和被修改的 `checks/` query builder

## 数据流

```text
date range + price/calendar tables -> read-only checks -> issue rows
                                   -> check_run summary
```

## 修改检查

- detection query 与 issue persistence 分层；query helper 不产生副作用。
- issue 必须保留 target table、instrument/date、severity、details 和 open status。
- 缺失检测基于已加载 instrument scope，避免把未建 universe 的标的误报为缺失。
- 新 issue type 要明确进入 repair、quarantine 或人工 review 的哪条路径。
- `asset_type_mismatch` 进入 `j21 migrate daily-price-asset-types` copy/verify/delete 路径，
  不得当作坏价格直接 quarantine。
- 不因 validator 重跑而静默关闭旧 issue；resolution 属于确认式 workflow。
- 运行 quality query 和 validation tests。
