"use client";

import { useState } from "react";
import { JsonEditor } from "./editor-controls";
import type { AuthorTestSuite } from "./editor-types";

export function AuthorTestStudio({
  tests,
  suite,
  onChange,
  onRun,
}: {
  tests: Array<Record<string, unknown>>;
  suite?: AuthorTestSuite;
  onChange: (tests: Array<Record<string, unknown>>) => void;
  onRun: () => Promise<AuthorTestSuite | undefined>;
}) {
  const [running, setRunning] = useState(false);
  async function run() {
    setRunning(true);
    try {
      await onRun();
    } finally {
      setRunning(false);
    }
  }
  return (
    <div className="authorTestWorkspace">
      <section className="panel stack">
        <div className="authorTestHead">
          <div>
            <p className="eyebrow">确定性试玩测试</p>
            <h2>把关键承诺写成可重复测试</h2>
          </div>
          <button className="button primary" disabled={running} onClick={() => void run()}>
            {running ? "正在执行…" : "运行全部测试"}
          </button>
        </div>
        <p className="studioHint">
          每条测试会创建隔离的内存存档，可预置玩家、关系、知识、任务与剧情线，再执行最多 20
          个真实行动。测试不会调用外部模型，也不会读取文件、网络或数据库。公开发布至少需要一条声明测试。
        </p>
        <div className="authorTestEditor">
          <JsonEditor
            key={JSON.stringify(tests)}
            label="玩法测试定义"
            value={tests}
            onApply={(value) => onChange(value as Array<Record<string, unknown>>)}
          />
        </div>
      </section>
      <section className="authorTestResults" aria-live="polite">
        {!suite && (
          <div className="empty">
            <h3>尚未运行</h3>
            <p>先保存测试定义，再运行完整编译与玩法测试。失败结果会显示实际值与期望值。</p>
          </div>
        )}
        {suite && (
          <div className={suite.passed ? "testSummary pass" : "testSummary fail"}>
            <b>{suite.passed ? "全部通过" : `${suite.failed_count} 项失败`}</b>
            <span>
              {suite.passed_count}/{suite.total} · {suite.duration_ms} ms · {suite.declared_tests}{" "}
              条声明测试
            </span>
          </div>
        )}
        {suite?.results.map((test) => (
          <article className={`testCase ${test.passed ? "pass" : "fail"}`} key={test.key}>
            <header>
              <div>
                <b>{test.name}</b>
                <code>{test.key}</code>
              </div>
              <span>
                {test.passed ? "PASS" : "FAIL"} · {test.duration_ms} ms · {test.actions_run} actions
              </span>
            </header>
            {test.error && <p className="error">{test.error}</p>}
            {test.assertions.map((assertion, index) => (
              <div className="testAssertion" key={`${assertion.path}-${index}`}>
                <span className={assertion.passed ? "testPass" : "testFail"}>
                  {assertion.passed ? "✓" : "×"}
                </span>
                <code>
                  {assertion.path} {assertion.op}
                </code>
                {!assertion.passed && (
                  <small>
                    期望 {JSON.stringify(assertion.expected)}，实际{" "}
                    {JSON.stringify(assertion.actual)}
                  </small>
                )}
              </div>
            ))}
          </article>
        ))}
      </section>
    </div>
  );
}
