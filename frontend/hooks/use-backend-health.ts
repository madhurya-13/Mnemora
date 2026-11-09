"use client";

import { useEffect, useState } from "react";
import { getHealth } from "@/lib/api";

type HealthState = "checking" | "connected" | "disconnected";

export function useBackendHealth() {
  const [state, setState] = useState<HealthState>("checking");
  const [version, setVersion] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getHealth().then((health) => {
      if (active) { setVersion(health.version); setState("connected"); }
    }).catch(() => { if (active) setState("disconnected"); });
    return () => { active = false; };
  }, []);

  return { state, version };
}
