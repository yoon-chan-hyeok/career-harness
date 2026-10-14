import type { Request } from "./api-client";

export async function downloadPrivateExport(request: Request) {
  const data = await request("/export");
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(data, null, 2)], {
      type: "application/json",
    }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = "career-private-export.json";
  try {
    link.click();
  } finally {
    // Give the browser time to begin the download before releasing the URL.
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
