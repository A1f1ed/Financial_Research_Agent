import type { Metadata, Viewport } from 'next';
import './globals.css';
import './agent.css';
import { FolioAgentProvider } from '../components/folio-agent-provider';
export const metadata: Metadata = { title: 'Folio — AI 金融研究工作台', description: '从一个问题到一份洞察。Folio AI 金融研究工作台，探索公司、行业与市场。' };
export const viewport: Viewport = { width: 'device-width', initialScale: 1, themeColor: '#f7f8fa' };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="zh-CN"><body><FolioAgentProvider>{children}</FolioAgentProvider></body></html>; }
