import { cn } from "../../lib/utils";
export function Badge({ children, className }: { children: React.ReactNode; className?: string }) { return <span className={cn("inline-flex items-center rounded-full border border-white/10 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-mist", className)}>{children}</span>; }
