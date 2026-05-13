"use client";

import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { ButtonHTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/cn";

const buttonStyles = cva(
  "inline-flex items-center justify-center gap-2 rounded-lg text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--color-accent) focus-visible:ring-offset-2 focus-visible:ring-offset-(--color-bg)",
  {
    variants: {
      variant: {
        default:
          "bg-(--color-accent) text-slate-950 hover:bg-emerald-400 active:bg-emerald-500",
        secondary:
          "bg-(--color-panel) text-(--color-text) border border-(--color-line) hover:bg-slate-800 active:bg-slate-700",
        ghost:
          "bg-transparent text-(--color-text) hover:bg-(--color-panel) active:bg-slate-800",
        outline:
          "bg-transparent text-(--color-text) border border-(--color-line) hover:bg-(--color-panel) active:bg-slate-800",
        danger:
          "bg-(--color-danger) text-white hover:bg-rose-600 active:bg-rose-700",
      },
      size: {
        sm: "h-8 px-3 text-xs",
        md: "h-9 px-4",
        lg: "h-10 px-5",
        icon: "h-9 w-9 p-0",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "md",
    },
  }
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonStyles> {
  asChild?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp className={cn(buttonStyles({ variant, size }), className)} ref={ref} {...props} />
    );
  }
);
Button.displayName = "Button";
