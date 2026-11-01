'use client';
import { ArrowDownRight, ArrowRight, ArrowUpRight, ChevronDown, Globe2, Plus, Radio, TrendingUp } from 'lucide-react';
import { useState } from 'react';
const markets = [{ name: '标普 500', ticker: 'S&P 500', value: '5,892.16', change: '+0.82%', up: true }, { name: '纳斯达克', ticker: 'NASDAQ', value: '18,421.09', change: '+1.24%', up: true }, { name: '道琼斯', ticker: 'DJIA', value: '42,628.18', change: '−0.15%', up: false }];
const stocks = [{ ticker: 'NVDA', name: '英伟达', price: '138.85', change: '+2.34%', color: 'nvidia' }, { ticker: 'AAPL', name: '苹果', price: '225.12', change: '+0.68%', color: 'apple' }, { ticker: 'MSFT', name: '微软', price: '428.76', change: '+1.12%', color: 'microsoft' }];
export function MarketPanel({ onResearch }: { onResearch: (prompt: string) => void }) {
 const [watchAll, setWatchAll] = useState(false);
 return <aside className="market-panel"><div className="panel-title"><h2>市场速览</h2><span className="sample-tag">示例数据</span></div><div className="market-session"><span><i/>美股市场</span><span>收盘 <ChevronDown size={12}/></span></div>
 <div className="indices">{markets.map(m => <div className="index-row" key={m.ticker}><div><strong>{m.name}</strong><small>{m.ticker}</small></div><div className="index-value"><strong>{m.value}</strong><small className={m.up ? 'positive' : 'negative'}>{m.up ? <ArrowUpRight size={12}/> : <ArrowDownRight size={12}/>} {m.change}</small></div></div>)}</div>
 <div className="watchlist-heading"><h2>我的关注</h2><button aria-label="探索关注标的" onClick={() => setWatchAll(!watchAll)}><Plus size={16}/></button></div>
 <div className="watchlist">{[...stocks, ...(watchAll ? [{ ticker: 'GOOGL', name: '谷歌', price: '175.30', change: '+0.92%', color: 'google' }] : [])].map(s => <button className="stock-row" key={s.ticker} onClick={() => onResearch(`请分析${s.name}（${s.ticker}）的投资价值及主要风险`)}><span className={`stock-logo ${s.color}`}>{s.ticker === 'NVDA' ? <TrendingUp size={19}/> : s.ticker === 'MSFT' ? <span className="ms-logo"><i/><i/><i/><i/></span> : s.ticker === 'AAPL' ? 'a' : 'G'}</span><span className="stock-name"><strong>{s.ticker}</strong><small>{s.name}</small></span><span className="stock-price"><strong>{s.price}</strong><small className="positive">{s.change}</small></span></button>)}</div>
 <button className="market-link" onClick={() => setWatchAll(!watchAll)}>{watchAll ? '收起关注列表' : '查看全部关注'}<ArrowRight size={13}/></button>
 <div className="insight-card"><span className="eyebrow"><Radio size={13}/> MARKET PULSE</span><h3>今天，市场在关注什么？</h3><p>AI 资本开支持续升温，科技巨头的下一轮增长从何而来？</p><button onClick={() => onResearch('AI 资本开支持续升温，科技巨头的下一轮增长从何而来？')}>探索研究主题<ArrowUpRight size={15}/></button><div className="pulse-decoration" aria-hidden="true"><span/><span/><span/><span/><span/><span/><span/><span/><span/><span/><span/><span/><span/></div></div>
 <div className="data-note"><Globe2 size={13}/><span>行情仅为界面演示，非实时数据<br/>不构成任何投资建议</span></div>
 </aside>;
}
