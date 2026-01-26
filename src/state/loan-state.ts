export class LoanState {
  private state: DurableObjectState;

  constructor(state: DurableObjectState) {
    this.state = state;
  }

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === "POST" && url.pathname === "/save") {
      const body = await request.json();
      await this.state.storage.put("state", body);
      return Response.json({ ok: true });
    }

    if (request.method === "GET" && url.pathname === "/get") {
      const data = await this.state.storage.get("state");
      return Response.json(data ?? null);
    }

    return new Response("Not Found", { status: 404 });
  }
}
