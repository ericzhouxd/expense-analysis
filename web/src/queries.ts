import { useQuery, useQueryClient } from "@tanstack/react-query";

import { type Bootstrap, type Choices, get, type Overview } from "./api";
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
    rules: data.rules,
    merchants: data.merchants,
    merchantNames: data.merchant_names,
  };
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
