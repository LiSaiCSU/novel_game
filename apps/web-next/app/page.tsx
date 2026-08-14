import Image from "next/image";
import Link from "next/link";
import {
  ArrowRight,
  BookMarked,
  CheckCircle2,
  GitBranch,
  PenTool,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

export default function Home() {
  return (
    <>
      <section className="hero">
        <Image
          src="/og.png"
          alt="春日黄昏的月见馆前，成年大学生们围绕修缮图纸与一封旧信共同工作"
          fill
          priority
          sizes="100vw"
        />
        <div className="heroShade" />
        <div className="heroCopy eyebrowLight">
          <p className="eyebrow">AI NARRATIVE WORLDS · 公开测试</p>
          <h1>
            故事不会等你
            <br />
            翻到下一页。
          </h1>
          <p>它会记住你的承诺、拒绝与沉默。进入一个持续运转的世界，或亲手创造自己的。</p>
          <div className="actions">
            <Link className="button primary" href="/library">
              探索作品 <ArrowRight size={18} />
            </Link>
            <Link className="button glass" href="/creator">
              开始创作
            </Link>
          </div>
          <div className="heroTrust" aria-label="核心能力">
            <span>自由输入行动</span>
            <span>版本锁定存档</span>
            <span>人物知识隔离</span>
          </div>
        </div>
      </section>
      <section className="intro section">
        <p className="eyebrow">不是选项树，是活着的世界</p>
        <h2>你的每次行动，都成为世界真正发生过的事。</h2>
        <div className="featureGrid">
          <article>
            <GitBranch />
            <h3>自由行动</h3>
            <p>不必寻找正确选项。用自己的话行动，世界按规则回应。</p>
          </article>
          <article>
            <BookMarked />
            <h3>长期记忆</h3>
            <p>人物只知道他们亲历或获知的事，也会记住重要关系。</p>
          </article>
          <article>
            <ShieldCheck />
            <h3>可信因果</h3>
            <p>模型负责表达，规则和数据库守住事实、边界与后果。</p>
          </article>
          <article>
            <Sparkles />
            <h3>创作者引擎</h3>
            <p>从地点图到人物秘密，在网页创作台完成校验和发布。</p>
          </article>
        </div>
      </section>
      <section className="storyFlow section" aria-labelledby="story-flow-title">
        <div className="storyFlowIntro">
          <p className="eyebrow">一次行动如何成为故事</p>
          <h2 id="story-flow-title">自由表达，但世界有可靠的边界。</h2>
          <p>
            你不需要猜编剧准备了哪个按钮。引擎会先判断人物、地点、物品与关系中的事实，再让模型把真实结果写成下一段叙事。
          </p>
          <Link className="textLink darkLink" href="/library">
            从一部作品开始 <ArrowRight size={16} />
          </Link>
        </div>
        <ol className="storyFlowSteps">
          <li>
            <span>01</span>
            <div>
              <b>说出你真正想做的事</b>
              <p>输入一句自然语言，或从情境建议中找到灵感。</p>
            </div>
          </li>
          <li>
            <span>02</span>
            <div>
              <b>世界先结算事实与后果</b>
              <p>规则检查能力、时间、知识边界与人物意愿。</p>
            </div>
          </li>
          <li>
            <span>03</span>
            <div>
              <b>叙事继续，选择被记住</b>
              <p>模型负责表达，规范状态会进入你的长期存档。</p>
            </div>
          </li>
        </ol>
      </section>
      <section className="spotlight section">
        <div>
          <p className="eyebrow">本季官方作品</p>
          <h2>《春日坂未完通信》</h2>
          <p>
            一封寄错二十年的信，一座十二周后关闭的旧礼堂。你刚来到春日坂大学，就被卷入一场关于记忆、选择与告别的校庆企划。
          </p>
          <div className="chips">
            <span>大学校园</span>
            <span>女性向</span>
            <span>主线 + 自由互动</span>
            <span>16+</span>
          </div>
          <Link className="textLink" href="/library">
            查看作品详情 <ArrowRight size={16} />
          </Link>
        </div>
        <blockquote>
          “保存一座建筑，不是让它永远停在过去。是让仍在这里的人，有权决定下一段故事。”
        </blockquote>
      </section>
      <section className="creatorCallout section">
        <div>
          <p className="eyebrow">FOR CREATORS</p>
          <h2>把世界写成规则，也保留故事的呼吸。</h2>
          <p>
            用地点图、人物知识、任务线与声明式规则搭建作品；实时诊断引用，隔离预览，再发布不可变版本。
          </p>
          <div className="creatorChecks">
            <span>
              <CheckCircle2 size={16} /> 自动保存与冲突保护
            </span>
            <span>
              <CheckCircle2 size={16} /> 结构校验与玩法测试
            </span>
            <span>
              <CheckCircle2 size={16} /> 审核、版本与导入导出
            </span>
          </div>
        </div>
        <Link className="creatorCta" href="/creator">
          <PenTool aria-hidden="true" />
          <span>
            <small>打开创作台</small>
            <b>开始建立你的第一个世界</b>
          </span>
          <ArrowRight aria-hidden="true" />
        </Link>
      </section>
    </>
  );
}
