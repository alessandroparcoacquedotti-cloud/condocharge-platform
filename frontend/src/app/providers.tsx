import type { ReactNode } from "react";

type Props = {
  children: ReactNode;
};

export default function AppProviders({ children }: Props) {
  return children;
}
