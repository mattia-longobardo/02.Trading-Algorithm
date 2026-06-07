"use client";

import { InputHTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/cn";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-9 w-full rounded-lg border border-(--color-line) bg-(--color-field) px-3 text-sm text-(--color-text) placeholder:text-(--color-muted) transition-colors hover:border-(--color-muted) focus:outline-none focus:border-(--color-accent) focus:ring-2 focus:ring-(--color-accent)/40 focus:ring-offset-0 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:border-(--color-line) aria-invalid:border-(--color-danger) aria-invalid:focus:ring-(--color-danger)/40",
        className
      )}
      {...props}
    />
  )
);
Input.displayName = "Input";
