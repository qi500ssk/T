"use client";

import { useEffect } from "react";

import { applyAppearance, readAppearance } from "@/lib/appearance";


export default function AppearanceController() {
  useEffect(() => applyAppearance(readAppearance()), []);
  return null;
}
