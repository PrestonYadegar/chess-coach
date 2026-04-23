import { redirect } from "next/navigation";

export default function PatternsRedirect({
  params,
}: {
  params: { username: string };
}) {
  redirect(`/players/${encodeURIComponent(decodeURIComponent(params.username))}`);
}
