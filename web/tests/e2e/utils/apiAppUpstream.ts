import http from "http";
import type { AddressInfo } from "net";

/**
 * A ticket API that custom API apps call in E2E specs. It serves an OpenAPI
 * spec, a GraphQL endpoint that answers introspection, and the REST endpoints
 * of the spec, and it records each request.
 *
 * The backend must reach it. It uses the host variables of the MCP test
 * servers: CI binds to 0.0.0.0 and the backend containers call
 * host.docker.internal. The backend's SSRF guard blocks loopback, so a local
 * run sets MCP_TEST_SERVER_PUBLIC_HOST to a private address of this machine,
 * and the backend sets MCP_SERVER_ALLOW_PRIVATE_NETWORK=true, as CI does.
 */

const BIND_HOST =
  process.env.MCP_TEST_SERVER_BIND_HOST ||
  process.env.MCP_TEST_SERVER_HOST ||
  "127.0.0.1";
const PUBLIC_HOST = process.env.MCP_TEST_SERVER_PUBLIC_HOST || BIND_HOST;

export const TICKET_ACTIONS = {
  read: { operationId: "get_ticket", summary: "Read a ticket" },
  create: { operationId: "create_ticket", summary: "Create a ticket" },
} as const;

export interface UpstreamRequest {
  method: string;
  path: string;
  authorization: string | undefined;
  body: string;
}

/** The OpenAPI spec of the ticket API, with one server URL. */
export function ticketsOpenApiSpec(title: string, serverUrl: string): object {
  return {
    openapi: "3.0.0",
    info: { title, description: `${title} API`, version: "1.0.0" },
    servers: [{ url: serverUrl }],
    paths: {
      "/tickets/{id}": {
        get: {
          ...TICKET_ACTIONS.read,
          parameters: [
            {
              name: "id",
              in: "path",
              required: true,
              schema: { type: "string" },
            },
          ],
          responses: { "200": { description: "The ticket" } },
        },
      },
      "/tickets": {
        post: {
          ...TICKET_ACTIONS.create,
          requestBody: {
            required: true,
            content: {
              "application/json": {
                schema: {
                  type: "object",
                  properties: { title: { type: "string" } },
                  required: ["title"],
                },
              },
            },
          },
          responses: { "201": { description: "The new ticket" } },
        },
      },
    },
  };
}

/** The same spec as YAML, as an admin uploads it. */
export function ticketsOpenApiYaml(title: string, serverUrl: string): string {
  return `openapi: 3.0.0
info:
  title: ${title}
  description: ${title} API
  version: 1.0.0
servers:
  - url: ${serverUrl}
paths:
  /tickets/{id}:
    get:
      operationId: ${TICKET_ACTIONS.read.operationId}
      summary: ${TICKET_ACTIONS.read.summary}
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
      responses:
        "200":
          description: The ticket
  /tickets:
    post:
      operationId: ${TICKET_ACTIONS.create.operationId}
      summary: ${TICKET_ACTIONS.create.summary}
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                title:
                  type: string
              required:
                - title
      responses:
        "201":
          description: The new ticket
`;
}

type TypeRef =
  | { kind: "SCALAR" | "OBJECT"; name: string; ofType: null }
  | { kind: "NON_NULL"; name: null; ofType: TypeRef };

const scalar = (name: string): TypeRef => ({
  kind: "SCALAR",
  name,
  ofType: null,
});
const object = (name: string): TypeRef => ({
  kind: "OBJECT",
  name,
  ofType: null,
});
const nonNull = (ofType: TypeRef): TypeRef => ({
  kind: "NON_NULL",
  name: null,
  ofType,
});

function objectType(
  name: string,
  fields: { name: string; type: TypeRef; args?: [string, TypeRef][] }[]
): object {
  return {
    kind: "OBJECT",
    name,
    description: null,
    fields: fields.map((field) => ({
      name: field.name,
      description: null,
      args: (field.args ?? []).map(([argName, type]) => ({
        name: argName,
        description: null,
        type,
        defaultValue: null,
      })),
      type: field.type,
      isDeprecated: false,
      deprecationReason: null,
    })),
    inputFields: null,
    interfaces: [],
    enumValues: null,
    possibleTypes: null,
  };
}

function scalarType(name: string): object {
  return {
    kind: "SCALAR",
    name,
    description: null,
    fields: null,
    inputFields: null,
    interfaces: null,
    enumValues: null,
    possibleTypes: null,
  };
}

/** The introspection answer of the schema:
 * `type Ticket { id: ID! title: String! }`,
 * `type Query { ticket(id: ID!): Ticket }` and
 * `type Mutation { ticketClose(id: ID!): Ticket }`. */
const INTROSPECTION_RESULT = {
  data: {
    __schema: {
      queryType: { name: "Query" },
      mutationType: { name: "Mutation" },
      subscriptionType: null,
      types: [
        objectType("Ticket", [
          { name: "id", type: nonNull(scalar("ID")) },
          { name: "title", type: nonNull(scalar("String")) },
        ]),
        objectType("Query", [
          {
            name: "ticket",
            type: object("Ticket"),
            args: [["id", nonNull(scalar("ID"))]],
          },
        ]),
        objectType("Mutation", [
          {
            name: "ticketClose",
            type: object("Ticket"),
            args: [["id", nonNull(scalar("ID"))]],
          },
        ]),
        scalarType("ID"),
        scalarType("String"),
      ],
      directives: [],
    },
  },
};

function readBody(request: http.IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    request.on("data", (chunk: Buffer) => chunks.push(chunk));
    request.on("end", () => resolve(Buffer.concat(chunks).toString()));
    request.on("error", reject);
  });
}

function sendJson(
  response: http.ServerResponse,
  status: number,
  body: unknown
): void {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(body));
}

export class ApiAppUpstream {
  readonly requests: UpstreamRequest[] = [];
  private readonly server: http.Server;
  private origin = "";

  private constructor() {
    this.server = http.createServer((request, response) => {
      void this.handle(request, response).catch((error: unknown) => {
        sendJson(response, 500, { error: String(error) });
      });
    });
  }

  static async start(): Promise<ApiAppUpstream> {
    const upstream = new ApiAppUpstream();
    await new Promise<void>((resolve, reject) => {
      upstream.server.once("error", reject);
      upstream.server.listen(0, BIND_HOST, () => resolve());
    });
    const { port } = upstream.server.address() as AddressInfo;
    upstream.origin = `http://${PUBLIC_HOST}:${port}`;
    return upstream;
  }

  /** The base URL of the REST endpoints. */
  get apiBaseUrl(): string {
    return `${this.origin}/api`;
  }

  /** Where the OpenAPI spec is, with `title` as its title. */
  specUrl(title: string): string {
    return `${this.origin}/openapi.json?title=${encodeURIComponent(title)}`;
  }

  get graphqlUrl(): string {
    return `${this.origin}/graphql`;
  }

  /** The recorded requests to the REST endpoints whose body or path has
   * `text`. */
  apiRequestsWith(text: string): UpstreamRequest[] {
    return this.requests.filter(
      (request) =>
        request.path.startsWith("/api/") &&
        (request.path.includes(text) || request.body.includes(text))
    );
  }

  async stop(): Promise<void> {
    await new Promise<void>((resolve) => this.server.close(() => resolve()));
  }

  private async handle(
    request: http.IncomingMessage,
    response: http.ServerResponse
  ): Promise<void> {
    const url = new URL(request.url ?? "/", this.origin);
    const body = await readBody(request);
    const method = request.method ?? "GET";
    this.requests.push({
      method,
      path: url.pathname,
      authorization: request.headers.authorization,
      body,
    });

    if (method === "GET" && url.pathname === "/openapi.json") {
      const title = url.searchParams.get("title") ?? "Tickets";
      sendJson(response, 200, ticketsOpenApiSpec(title, this.apiBaseUrl));
      return;
    }
    if (method === "POST" && url.pathname === "/graphql") {
      if (body.includes("__schema")) {
        sendJson(response, 200, INTROSPECTION_RESULT);
        return;
      }
      sendJson(response, 200, { data: { ticket: null } });
      return;
    }
    const ticket = /^\/api\/tickets\/([^/]+)$/.exec(url.pathname);
    if (method === "GET" && ticket?.[1]) {
      const id = decodeURIComponent(ticket[1]);
      sendJson(response, 200, { id, title: `Ticket ${id}` });
      return;
    }
    if (method === "POST" && url.pathname === "/api/tickets") {
      sendJson(response, 201, { id: "created", ...JSON.parse(body || "{}") });
      return;
    }
    sendJson(response, 404, { error: "Not found" });
  }
}
