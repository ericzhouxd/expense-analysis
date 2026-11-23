import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { type Bootstrap, type Choices, get, type Overview, post, type Suggestion } from "./api";
import type { Vocabulary } from "./lib/quickParse";

export function useBootstrap() {
  return useQuery({ queryKey: ["bootstrap"], queryFn: () => get<Bootstrap>("/api/bootstrap") });
}

export function useChoices() {
  return useQuery({ queryKey: ["choices"], queryFn: () => get<Choices>("/api/choices") });
}

/** After any write, every derived number may change: refetch whatever is on screen. */
export function useRefresh(): () => Promise<void> {
  const client = useQueryClient();
  return () => client.invalidateQueries();
}

export function vocabularyOf(data: Bootstrap): Vocabulary {
  return {
    today: data.today,
    categories: data.categories.map((category) => category.name),
    accounts: data.accounts,
    paymentMethods: data.payment_methods,
    merchantNames: data.merchant_names,
  };
}

const TYPING_MS = 120;

/** What the app would file this under, kept up with while it is typed. */
export function useSuggestion(description: string, merchant: string, transactionType: string) {
  const asked = JSON.stringify({ description: description.trim(), merchant, transaction_type: transactionType });
  const [settled, setSettled] = useState(asked);
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(asked), TYPING_MS);
    return () => window.clearTimeout(timer);
  }, [asked]);
  const body = JSON.parse(settled) as { description: string };
  return useQuery({
    queryKey: ["suggest", settled],
    queryFn: () => post<Suggestion>("/api/suggest", body),
    enabled: body.description.length > 0,
    placeholderData: (previous) => (body.description ? previous : undefined),
  });
}

export function useOverview(month: string | null, scope: "everyday" | "all") {
  const params = new URLSearchParams({ scope });
  if (month) params.set("month", month);
  return useQuery({
    queryKey: ["overview", month ?? "", scope],
    queryFn: () => get<Overview>(`/api/overview?${params}`),
    placeholderData: (previous) => previous,
  });
}
