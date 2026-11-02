# 智能体工程任务包模板

## 最小模板

```yaml
task_id: <stable-id>
objective: <可观察结果>
non_goals:
  - <明确不做什么>
baseline:
  code: <commit/tag/path+hash>
  model_data: <path+hash/not-applicable>
  hardware: <BIT/HWH/hash/not-applicable>
  tools: <versions>
allowed_paths:
  - <可修改位置>
read_only_paths:
  - <合同与证据位置>
interface_refs:
  - <当前接口、数据布局、复位或指标定义>
context_refs:
  - <最小充分日志、报告、失败材料>
skills:
  - <本次调用的 Skill>
acceptance:
  - stage: <static/golden/sim/implementation/board/system/document>
    check: <命令或明确人工检查>
    expected: <可判定结果>
budgets:
  max_edit_test_loops: 3
  max_same_error_retries: 2
  command_timeout_seconds: <local-value>
approval:
  required_before: <architecture/install/delete/board/publish/...>
artifacts_to_record:
  - <diff/log/report/hash/case>
status: PLAN
```

## 字段使用规则

- `objective` 写可观察结果，不写“优化一下”。
- `non_goals` 防止为提高指标顺带改变模型、阈值、接口或测试语义。
- `allowed_paths` 是实际写入边界；`read_only_paths` 中的合同不得为方便通过而修改。
- `interface_refs` 和真实日志优先于模型记忆。
- `acceptance` 声明最高验证层；只完成低层时不得按高层交付。
- `budgets` 应由执行环境实际约束；只写在提示词里不算强制执行。
- `approval` 标明必须等待人的状态转换。
- `skills` 只列真正使用的流程，避免把相关 Skill 全部堆入上下文。

## 失败反馈包

```yaml
run_id: <id>
failed_stage: <stage>
command: <redacted-command>
exit_code: <code>
first_error: <首个关键错误>
log_ref: <path>
current_diff: <path+hash>
failing_cases:
  - <case>
allowed_next_change: <单一主要假设；无法确定则 NEEDS_HUMAN>
retry_index: <n>
```

## 交接回执

```yaml
status: <COMPLETE/PASS_WITH_NOTES/FAILED/BLOCKED/NEEDS_HUMAN>
changes:
  - <实际修改及理由>
verification:
  highest_stage: <stage>
  evidence_refs:
    - <真实产物>
human_decisions:
  - <需求、风险或验收决定>
failed_or_superseded:
  - <保留有价值失败>
limitations:
  - <未覆盖范围>
cleanup: <进程、设备、缓冲、临时文件状态>
next_owner_action: <单一明确接续动作>
```

## 文档／Skill 任务的最小验收

非代码任务也需要可判定验收：frontmatter 合法、相对链接存在、来源分类正确、关键数字回指证据、无未标占位的完成声明、未把桌面检查写成独立复验、新增文件未越出授权目录。
