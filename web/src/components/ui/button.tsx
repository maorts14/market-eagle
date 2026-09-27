import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/utils";
const buttonVariants = cva("inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50", { variants: { variant: { default: "bg-lime text-[#10150A] hover:bg-[#CDFD73]", outline: "border border-line bg-transparent text-slate-100 hover:bg-white/5", ghost: "text-mist hover:text-white hover:bg-white/5" }, size: { default: "h-9 px-3.5", sm: "h-8 px-3", icon: "h-9 w-9" } }, defaultVariants: { variant: "default", size: "default" } });
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> { asChild?: boolean }
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, asChild = false, ...props }, ref) => { const Comp = asChild ? Slot : "button"; return <Comp className={cn(buttonVariants({ variant, size }), className)} ref={ref} {...props} />; });
Button.displayName = "Button";
