import Image from "next/image";
import Link from "next/link";
import { ArrowRight, BookMarked, GitBranch, ShieldCheck, Sparkles } from "lucide-react";

export default function Home() {
  return <>
    <section className="hero">
      <Image src="/og.png" alt="春日黄昏的月见馆前，成年大学生们围绕修缮图纸与一封旧信共同工作" fill priority sizes="100vw" />
      <div className="heroShade" />
      <div className="heroCopy eyebrowLight">
        <p className="eyebrow">AI NARRATIVE WORLDS · 公开测试</p>
        <h1>故事不会等你<br />翻到下一页。</h1>
        <p>它会记住你的承诺、拒绝与沉默。进入一个持续运转的世界，或亲手创造自己的。</p>
        <div className="actions"><Link className="button primary" href="/library">探索作品 <ArrowRight size={18}/></Link><Link className="button glass" href="/creator">开始创作</Link></div>
      </div>
    </section>
    <section className="intro section">
      <p className="eyebrow">不是选项树，是活着的世界</p>
      <h2>你的每次行动，都成为世界真正发生过的事。</h2>
      <div className="featureGrid">
        <article><GitBranch/><h3>自由行动</h3><p>不必寻找正确选项。用自己的话行动，世界按规则回应。</p></article>
        <article><BookMarked/><h3>长期记忆</h3><p>人物只知道他们亲历或获知的事，也会记住重要关系。</p></article>
        <article><ShieldCheck/><h3>可信因果</h3><p>模型负责表达，规则和数据库守住事实、边界与后果。</p></article>
        <article><Sparkles/><h3>创作者引擎</h3><p>从地点图到人物秘密，在网页创作台完成校验和发布。</p></article>
      </div>
    </section>
    <section className="spotlight section">
      <div><p className="eyebrow">本季官方作品</p><h2>《春日坂未完通信》</h2><p>一封寄错二十年的信，一座十二周后关闭的旧礼堂。你刚来到春日坂大学，就被卷入一场关于记忆、选择与告别的校庆企划。</p><div className="chips"><span>大学校园</span><span>女性向</span><span>主线 + 自由互动</span><span>16+</span></div><Link className="textLink" href="/library">查看作品详情 <ArrowRight size={16}/></Link></div>
      <blockquote>“保存一座建筑，不是让它永远停在过去。是让仍在这里的人，有权决定下一段故事。”</blockquote>
    </section>
  </>;
}
