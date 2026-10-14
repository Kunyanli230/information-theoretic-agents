# Information-theoretic agents

Stage 2 implements complete-message rate–distortion encoding and actual asynchronous delegation for coding agents. The default model combination is **Cursor CLI Grok 4.6** as the guide and a resident local **Qwen2.5-Coder-0.5B-Instruct** Transformers process as the executor.

See [the Stage 2 implementation and Chinese runbook](README_STAGE2.md) for setup, calibration, live execution and paired evaluation.

~~~bash
python -m unittest discover -s tests_stage2 -v
python -m voi_async demo
~~~

The demo uses synthetic model fixtures with real local code/test execution. Live model experiments require Cursor authentication and the pinned Qwen weights. Historical Stage 1 studies and drafts remain under [paper/](paper/README.md); Stage 2 calibration and results must be collected separately.
