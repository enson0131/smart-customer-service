import { DurableObject } from "cloudflare:workers";

export class Aftercare extends DurableObject {
  async ready() {
    const container = this.ctx.container;
    if (!container.running) {
      const { CF_ACCOUNT_ID, D1_DATABASE_ID, D1_API_TOKEN,
              DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL = "" } = this.env;
      if (!D1_API_TOKEN) throw new Error("D1_API_TOKEN is required");
      if (!DEEPSEEK_API_KEY?.trim()) throw new Error("DEEPSEEK_API_KEY is required");
      container.start({
        image: container.images.base, instance: "standard-1", enableInternet: true,
        env: { STORE_BACKEND: "d1", CF_ACCOUNT_ID, D1_DATABASE_ID, D1_API_TOKEN,
               DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL }
      });
    }
    await container.setInactivityTimeout(300000);
    const port = container.getTcpPort(8080);
    for (let i = 0; i < 100; i++) {
      try {
        const response = await port.fetch("http://container/health", {signal: AbortSignal.timeout(1000)});
        await response.body?.cancel();
        if (response.ok) return port;
      } catch { /* Python may still be starting. */ }
      await scheduler.wait(200);
    }
    throw new Error("Aftercare startup timed out");
  }

  async fetch(request) {
    this.starting ??= this.ready().finally(() => { this.starting = undefined; });
    const port = await this.starting;
    const url = new URL(request.url);
    url.protocol = "http:";
    url.host = "container";
    const forwarded = new Request(url, request);
    forwarded.headers.delete("host");
    return port.fetch(forwarded);
  }
}
export default {
  fetch(request, env) { return env.SERVICE.getByName("aftercare").fetch(request); }
};
