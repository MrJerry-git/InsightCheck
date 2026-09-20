import Image from "next/image";
import type { SystemKey } from "./domain";
export function Organ({kind,active=true}:{kind:SystemKey;active?:boolean}) {
 if(kind==='metabolic') return <svg className={`cs-organ ${active?'is-lit':''}`} viewBox="0 0 240 240" aria-hidden="true"><defs><radialGradient id="drop"><stop stopColor="#f1cd81"/><stop offset="1" stopColor="#b88539"/></radialGradient></defs><circle cx="120" cy="125" r="87" fill="#f4ead6"/><path d="M120 39C104 75 71 99 71 132A49 49 0 0 0 169 132C169 100 137 74 120 39Z" fill="url(#drop)"/><path d="M87 137Q90 158 109 168" fill="none" stroke="#ffebc0" strokeWidth="6" strokeLinecap="round"/></svg>;
 return <span className={`cs-organ cs-atlas ${kind} ${active?'is-lit':''}`} aria-hidden="true"/>;
}
export function Body({lit,onSelect}:{lit:Record<SystemKey,boolean>;onSelect:(key:SystemKey)=>void}) { return <div className="cs-body-figure"><Image src="/competition/anatomy.png" alt="完整人体肌肉解剖示意图，点亮仅表示资料已确认" width={1024} height={1536} priority className="cs-body-image"/>{(['heart','kidney'] as const).map(k=><button key={k} className={`cs-body-target ${k} ${lit[k]?'lit':''}`} aria-label={`${k==='heart'?'心血管健康':'肾功能'}：${lit[k]?'资料已确认，查看详情':'尚无已确认资料'}`} disabled={!lit[k]} onClick={()=>onSelect(k)}><Organ kind={k} active={lit[k]}/></button>)}<span className="cs-body-caption">FRONT VIEW · 正面示意</span></div>; }
export function Doctor(){ return <div className="cs-doctor" role="img" aria-label="虚构的检查规划助手形象，不代表真人医生审核"/>; }
