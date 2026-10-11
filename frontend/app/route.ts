import { readFile } from "node:fs/promises";
import { join } from "node:path";

// The public introduction is also packaged as an independent static demo.
// It needs neither a session nor a functioning API to explain the product.
export const dynamic = "force-static";
export async function GET() {
  const html = await readFile(join(process.cwd(), "public/showcase/index.html"), "utf8");
  return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8" } });
}
