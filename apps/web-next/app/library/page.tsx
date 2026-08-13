"use client";

import Image from "next/image";
import Link from "next/link";
import { Search } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Release = { id:string; slug:string; title:string; summary:string; version:string; locale:string; rating:string; tags:string[]; cover_url?:string|null; play_count:number };

export default function LibraryPage(){
  const [items,setItems]=useState<Release[]>([]); const [q,setQ]=useState(""); const [locale,setLocale]=useState(""); const [rating,setRating]=useState(""); const [sort,setSort]=useState("updated"); const [loading,setLoading]=useState(true); const [error,setError]=useState("");
  useEffect(()=>{const timer=setTimeout(()=>{setLoading(true);const query=new URLSearchParams({q,sort});if(locale)query.set("locale",locale);if(rating)query.set("rating",rating);api<{items:Release[]}>(`/catalog/releases?${query}`).then(r=>{setItems(r.items);setError("")}).catch(e=>setError(e.message)).finally(()=>setLoading(false))},250);return()=>clearTimeout(timer)},[q,locale,rating,sort]);
  return <div className="page"><div className="pageHead"><div><p className="eyebrow">WORLD LIBRARY</p><h1>找一个世界，留下你的版本。</h1><p>每部作品都固定在经过审核的发布版本上。你的存档不会因为作者更新而悄悄改变。</p></div><div className="libraryFilters"><label className="field" htmlFor="search"><span>搜索作品</span><div style={{position:"relative"}}><Search size={17} style={{position:"absolute",left:13,top:14,color:"#71656c"}}/><input id="search" className="input" style={{paddingLeft:40}} value={q} onChange={e=>setQ(e.target.value)} placeholder="标题、简介、标签"/></div></label><label className="field"><span>语言</span><select className="select" value={locale} onChange={event=>setLocale(event.target.value)}><option value="">全部</option><option value="zh-CN">简体中文</option><option value="ja-JP">日语</option></select></label><label className="field"><span>分级</span><select className="select" value={rating} onChange={event=>setRating(event.target.value)}><option value="">全部</option><option value="all">全年龄</option><option value="13+">13+</option><option value="16+">16+</option></select></label><label className="field"><span>排序</span><select className="select" value={sort} onChange={event=>setSort(event.target.value)}><option value="updated">最近更新</option><option value="popular">最受欢迎</option><option value="newest">最新发布</option></select></label></div></div>
    {error&&<p className="error" role="alert">{error}</p>}{loading?<div className="empty">正在整理书架…</div>:items.length===0?<div className="empty">还没有符合条件的公开作品。</div>:<div className="cardGrid">{items.map(item=><article className="workCard" key={item.id}><div className="workCover"><Image src={item.cover_url||"/og.png"} alt={`${item.title}封面`} fill sizes="(max-width:720px) 100vw, 33vw"/></div><div className="workBody"><div className="meta"><span>{item.rating}</span><span>{item.locale}</span><span>v{item.version}</span><span>{item.play_count} 局</span></div><h2>{item.title}</h2><p style={{color:"var(--muted)",lineHeight:1.7}}>{item.summary}</p><div className="chips">{item.tags.map(tag=><button type="button" key={tag} onClick={()=>setQ(tag)} aria-label={`筛选标签 ${tag}`}>{tag}</button>)}</div><Link className="textLink" href={`/library/${item.id}`}>查看作品 →</Link></div></article>)}</div>}
  </div>
}
