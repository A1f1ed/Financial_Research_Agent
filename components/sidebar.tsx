'use client';
import { ArrowUpRight, BookOpen, ChevronDown, CircleHelp, Clock3, Database, Ellipsis, FolderOpen, Layers3, Origami, Plus, Settings2, Sparkles, Star } from 'lucide-react';
export type View = 'workspace' | 'history' | 'saved' | 'sources';
export function Sidebar({ view, onView, onNew, onHelp, mobileOpen }: { view: View; onView: (view: View) => void; onNew: () => void; onHelp: () => void; mobileOpen: boolean }) {
  return <aside className={`sidebar ${mobileOpen ? 'mobile-open' : ''}`}>
    <a className="brand" href="/" aria-label="Folio 首页"><span className="brand-symbol"><Origami size={27} strokeWidth={1.7}/></span>folio<span className="brand-period">.</span><span className="brand-label">RESEARCH</span></a>
    <button className="workspace-switch" onClick={onHelp}><span className="workspace-avatar"><Layers3 size={17}/></span><span>个人工作空间<small>Personal workspace</small></span><ChevronDown size={14}/></button>
    <button className="new-research" onClick={onNew}><Plus size={17}/> 新建研究 <span>⌘ K</span></button>
    <nav aria-label="主导航">
      <button className={view === 'workspace' ? 'nav-item active' : 'nav-item'} onClick={() => onView('workspace')}><Sparkles size={18}/>研究工作台<span className="nav-dot"/></button>
      <button className={view === 'history' ? 'nav-item active' : 'nav-item'} onClick={() => onView('history')}><Clock3 size={18}/>研究历史<span className="nav-count">3</span></button>
      <button className={view === 'saved' ? 'nav-item active' : 'nav-item'} onClick={() => onView('saved')}><Star size={18}/>我的收藏</button>
      <button className={view === 'sources' ? 'nav-item active' : 'nav-item'} onClick={() => onView('sources')}><Database size={18}/>数据来源<span className="soon">预览</span></button>
    </nav>
    <div className="sidebar-section-label">研究空间 <button aria-label="关于研究空间" onClick={onHelp}><Plus size={14}/></button></div>
    <button className="nav-item folder" onClick={() => onView('history')}><FolderOpen size={17}/>美股科技观察<span>2</span></button>
    <button className="nav-item folder" onClick={() => onView('history')}><FolderOpen size={17}/>宏观与资产配置<span>1</span></button>
    <div className="sidebar-bottom"><div className="upgrade"><div><span className="upgrade-icon"><Sparkles size={16}/></span><strong>让研究更进一步</strong></div><p>更深入的分析，更清晰的决策。</p><button onClick={onHelp}>探索 Folio Pro <ArrowUpRight size={14}/></button></div>
      <button className="nav-item" onClick={onHelp}><CircleHelp size={17}/>帮助与使用指南<ArrowUpRight size={13}/></button>
      <div className="profile"><span className="profile-avatar">JL</span><div><strong>Jamie Lin</strong><small>个人版 · UI 演示</small></div><button aria-label="工作台设置" onClick={onHelp}><Settings2 size={17}/></button></div>
    </div>
  </aside>;
}
