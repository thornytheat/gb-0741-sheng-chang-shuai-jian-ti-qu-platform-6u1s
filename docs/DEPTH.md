# 深度登记 声场衰减提取台

- 中型项目，面向礼堂声学验收工程师。
- 核心规则为经校准的压力平方反向积分，以实测动态范围限制回归，给出可追溯的 T20 和 T30。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 脉冲响应收件 | 导入带时间索引的 CSV，定位缺点和矛盾 | `POST /api/intake` | `app/modules/m1_intake/reader.py` `app/modules/m1_intake/continuity.py` | `tests/test_intake.py` |
| M2 量纲校准 | 查看压力系数、直达声索引和来源行 | `GET /api/calibration/{source_id}` | `app/modules/m2_calibration/units.py` | `tests/test_calibration.py` |
| M3 能量衰减 | 检查扣噪后反向能量积分结果 | `GET /api/decay/{source_id}` | `app/modules/m3_decay/integral.py` `app/modules/m3_decay/segments.py` `app/modules/m3_decay/service.py` | `tests/test_decay.py` `tests/test_segments.py` |
| M4 拟合时段 | 读取 T20 与 T30 时间窗、回归系数及质量 | `GET /api/fit/{source_id}` | `app/modules/m4_fit/windows.py` `app/modules/m4_fit/regression.py` | `tests/test_fit.py` |
| M5 噪声判废 | 核对尾段噪声和两档动态范围 | `GET /api/noise/{source_id}` | `app/modules/m5_noise/gate.py` | `tests/test_noise.py` |
| M6 频段勾稽 | 对频带和采样行勾稽，查看双档差异 | `GET /api/reconcile/{source_id}` | `app/modules/m6_reconcile/service.py` `app/modules/m6_reconcile/comparison.py` | `tests/test_reconcile.py` |
| M7 复测归档 | 保存证据、重跑原输入并下载 | `POST /api/runs` | `app/modules/m7_archive/service.py` `app/modules/m7_archive/export.py` | `tests/test_archive.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现会怎样 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-01 | 参考样例使用 GB18030 | 中文备注无法解码 | UTF-8 失败后回退 | `app/modules/m1_intake/reader.py` | `tests/test_intake.py::test_reference_reads_gb18030` |
| TRAP-02 | 礼堂样例首列含 BOM | 首列匹配失败 | 使用 UTF-8-sig | `app/modules/m1_intake/reader.py` | `tests/test_intake.py::test_bom_and_multiline_keep_physical_sample_lines` |
| TRAP-03 | 500 Hz 峰值备注含换行 | 行号失去对应关系 | 记录 CSV 逻辑行的物理起点 | `app/modules/m1_intake/reader.py` | `tests/test_intake.py::test_bom_and_multiline_keep_physical_sample_lines` |
| TRAP-04 | 礼堂样例重复表头 | 将表头当成变更 | 独立统计表头 | `app/modules/m1_intake/reader.py` | `tests/test_intake.py::test_sample_counts_are_exclusive_and_remove_repeated_header` |
| TRAP-05 | 礼堂样例有短行 | 补列使索引错位 | 保留原值并标记 | `app/modules/m1_intake/reader.py` | `tests/test_intake.py::test_short_width_and_missing_amplitude_have_distinct_codes` |
| TRAP-06 | 500 Hz 峰值含全角数字与小数点 | 丢失直达声 | 规范字符后解析 | `app/modules/m1_intake/contract.py` | `tests/test_calibration.py::test_fullwidth_amplitude_is_normalized` |
| TRAP-07 | 63 Hz 幅值填 N/A | 当零参与积分 | 隔离样本及频带 | `app/modules/m1_intake/contract.py` | `tests/test_intake.py::test_short_width_and_missing_amplitude_have_distinct_codes` |
| TRAP-13 | 1000 Hz 两相邻样本到达乱序 | 用文件顺序改变时间轴 | 按采样序号重排 | `app/modules/m1_intake/continuity.py` | `tests/test_intake.py::test_arrival_order_reconstructed_by_sample_index` |
| TRAP-14 | 2000 Hz 同索引数值矛盾 | 后写覆盖，污染回归 | 整带隔离并列原值 | `app/modules/m1_intake/continuity.py` | `tests/test_intake.py::test_contradictory_duplicate_band_never_reaches_fit` |
| TRAP-15 | 礼堂样例 Pa、mPa、V、mV | 绝对噪声功率跨量纲 | 换算灵敏度与振幅增益 | `app/modules/m2_calibration/units.py` | `tests/test_calibration.py::test_voltage_gain_and_sensitivity_work_on_sample` |
| TRAP-16 | 2000 Hz 尾段截断 | 短尾误当背景噪声 | 核对声明长度 | `app/modules/m1_intake/continuity.py` | `tests/test_intake.py::test_missing_points_and_truncated_tail_are_different` |
| TRAP-18 | 零字节、全空与仅表头 | 记录空结果为成功 | 返回独立的文件级原因 | `app/modules/m1_intake/reader.py` | `tests/test_intake.py::test_empty_cases_raise_distinct_codes` |
| TRAP-19 | 测试中一个低块夹在可用区间 | 瞬态低块误判整个尾段 | 连续两块才截断 | `app/modules/m5_noise/gate.py` | `tests/test_noise.py::test_consecutive_low_blocks_cut_at_first_block` |
| TRAP-23 | 测试曲线阈值等于样本值 | 跳过等号或将越界点纳入 | 明确交点与回归右端排除 | `app/modules/m4_fit/windows.py` | `tests/test_fit.py::test_threshold_crossing_interpolates_and_has_exclusive_stop` |
| TRAP-24 | 坏行断开后直接拼接样本 | 缺口被当成零能量衰减，污染反向积分 | 按采样序号切连续段，段内严格 +1，绝不跨缺口拼接 | `app/modules/m1_intake/continuity.py` `app/modules/m3_decay/segments.py` | `tests/test_segments.py::test_build_segments_never_joins_across_index_gap` |
| TRAP-25 | 整带丢弃导致可用频带进不了验收 | 可估计的缩短段被一并报废 | 逐段过同一质量门槛，可估计段保留可追溯缩短结论 | `app/modules/m3_decay/segments.py` | `tests/test_segments.py::test_middle_gap_with_estimable_post_gap_run_is_shortened` |
| TRAP-26 | 矛盾重复值被当成可恢复缺点 | 用错误值补出看似连续的序列 | 完整性致命缺陷禁止缩短，整带退回补测 | `app/modules/m1_intake/continuity.py` | `tests/test_segments.py::test_contradictory_duplicate_is_fatal_and_never_shortened` |
| TRAP-27 | 评估重算改动收件原始计数 | 归档与 `/api/intake` 快照对不上 | 评估在工作副本上重分类采信/排除行，收件计数不变 | `app/modules/m6_reconcile/service.py` | `tests/test_e2e.py` |
| TRAP-28 | 采信规则更新后旧结论仍被复用 | 同源重跑悄悄沿用过期采信 | 规则版本入批次编号，版本不符 `VERSION_CHANGED` 作废重算 | `app/modules/m7_archive/service.py` `app/config.py` | `tests/test_archive.py::test_rule_version_change_invalidates_prior_archive` |

## 对账断言

礼堂样例共 8 个频带：4 个整带可拟合、1 个缩短采信（250 Hz，采信序号 101–1099 / 行 1202–2200，T20≈T30≈0.66 s）、1 个动态范围不足、2 个退回补测（63 Hz 两段分别尾段过短、深度不足；2000 Hz 矛盾重复致命）。排除采样行 399，频带及采样行差额均为零。8000 Hz 两档标差约 22.26%。存在退回补测频带时 `acceptance.acceptable=false`。
