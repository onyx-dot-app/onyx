import type {
  ASTNode,
  ArgumentNode,
  Statement,
  ParseError,
  Token,
} from "../types";
import { TokenType } from "../types";
import { Tokenizer } from "./tokenizer";

/**
 * Recursive descent parser for GenUI Lang.
 *
 * Grammar:
 *   program    = statement*
 *   statement  = identifier "=" expression NEWLINE
 *   expression = component | array | object | literal | reference
 *   component  = PascalCase "(" arglist? ")"
 *   arglist    = arg ("," arg)*
 *   arg        = namedArg | expression
 *   namedArg   = identifier ":" expression
 *   array      = "[" (expression ("," expression)*)? "]"
 *   object     = "{" (pair ("," pair)*)? "}"
 *   pair       = (identifier | string) ":" expression
 *   literal    = string | number | boolean | null
 *   reference  = camelCase identifier (doesn't start with uppercase)
 */
export class Parser {
  private tokens: Token[];
  private pos = 0;
  private errors: ParseError[] = [];

  constructor(tokens: Token[]) {
    this.tokens = tokens;
  }

  static fromSource(source: string): Parser {
    const tokenizer = new Tokenizer(source);
    return new Parser(tokenizer.tokenize());
  }

  parse(): { statements: Statement[]; errors: ParseError[] } {
    const statements: Statement[] = [];

    this.skipNewlines();

    while (!this.isAtEnd()) {
      try {
        const stmt = this.parseStatement();
        if (stmt) {
          statements.push(stmt);
        }
      } catch (e) {
        if (e instanceof ParseErrorException) {
          this.errors.push(e.toParseError());
        }
        // Skip to next line to recover
        this.skipToNextStatement();
      }
      this.skipNewlines();
    }

    return { statements, errors: this.errors };
  }

  private parseStatement(): Statement | null {
    if (this.isAtEnd()) return null;

    const ident = this.expect(TokenType.Identifier);
    this.expect(TokenType.Equals);
    const value = this.parseExpression();

    return { name: ident.value, value };
  }

  private parseExpression(): ASTNode {
    const token = this.current();

    if (token.type === TokenType.LBracket) {
      return this.parseArray();
    }

    if (token.type === TokenType.LBrace) {
      return this.parseObject();
    }

    if (token.type === TokenType.String) {
      this.advance();
      return { kind: "literal", value: token.value };
    }

    if (token.type === TokenType.Number) {
      this.advance();
      return { kind: "literal", value: Number(token.value) };
    }

    if (token.type === TokenType.Boolean) {
      this.advance();
      return { kind: "literal", value: token.value === "true" };
    }

    if (token.type === TokenType.Null) {
      this.advance();
      return { kind: "literal", value: null };
    }

    if (token.type === TokenType.Identifier) {
      const isPascalCase = /^[A-Z]/.test(token.value);

      if (isPascalCase && this.peek()?.type === TokenType.LParen) {
        return this.parseComponent();
      }

      // camelCase identifier = variable reference
      this.advance();
      return { kind: "reference", name: token.value };
    }

    throw this.error(`Unexpected token: ${token.type} "${token.value}"`);
  }

  private parseComponent(): ASTNode {
    const name = this.expect(TokenType.Identifier);
    this.expect(TokenType.LParen);

    const args: ArgumentNode[] = [];

    if (this.current().type !== TokenType.RParen) {
      args.push(this.parseArg());

      while (this.current().type === TokenType.Comma) {
        this.advance(); // skip comma
        if (this.current().type === TokenType.RParen) break; // trailing comma
        args.push(this.parseArg());
      }
    }

    this.expect(TokenType.RParen);

    return { kind: "component", name: name.value, args };
  }

  private parseArg(): ArgumentNode {
    // Look ahead: if we see `identifier ":"`, it's a named arg
    if (
      this.current().type === TokenType.Identifier &&
      this.peek()?.type === TokenType.Colon
    ) {
      // But only if the identifier is NOT PascalCase (which would be a component)
      const isPascalCase = /^[A-Z]/.test(this.current().value);
      if (!isPascalCase) {
        const key = this.current().value;
        this.advance(); // identifier
        this.advance(); // colon
        const value = this.parseExpression();
        return { key, value };
      }
    }

    // Positional argument
    const value = this.parseExpression();
    return { key: null, value };
  }

  private parseArray(): ASTNode {
    this.expect(TokenType.LBracket);

    const elements: ASTNode[] = [];

    if (this.current().type !== TokenType.RBracket) {
      elements.push(this.parseExpression());

      while (this.current().type === TokenType.Comma) {
        this.advance();
        if (this.current().type === TokenType.RBracket) break;
        elements.push(this.parseExpression());
      }
    }

    this.expect(TokenType.RBracket);

    return { kind: "array", elements };
  }

  private parseObject(): ASTNode {
    this.expect(TokenType.LBrace);

    const entries: { key: string; value: ASTNode }[] = [];

    if (this.current().type !== TokenType.RBrace) {
      entries.push(this.parseObjectEntry());

      while (this.current().type === TokenType.Comma) {
        this.advance();
        if (this.current().type === TokenType.RBrace) break;
        entries.push(this.parseObjectEntry());
      }
    }

    this.expect(TokenType.RBrace);

    return { kind: "object", entries };
  }

  private parseObjectEntry(): { key: string; value: ASTNode } {
    let key: string;

    if (this.current().type === TokenType.String) {
      key = this.current().value;
      this.advance();
    } else if (this.current().type === TokenType.Identifier) {
      key = this.current().value;
      this.advance();
    } else {
      throw this.error(`Expected object key, got ${this.current().type}`);
    }

    this.expect(TokenType.Colon);
    const value = this.parseExpression();

    return { key, value };
  }

  // ── Helpers ──

  private current(): Token {
    return (
      this.tokens[this.pos] ?? {
        type: TokenType.EOF,
        value: "",
        offset: -1,
        line: -1,
        column: -1,
      }
    );
  }

  private peek(): Token | undefined {
    return this.tokens[this.pos + 1];
  }

  private advance(): Token {
    const token = this.current();
    if (this.pos < this.tokens.length) this.pos++;
    return token;
  }

  private expect(type: TokenType): Token {
    const token = this.current();
    if (token.type !== type) {
      throw this.error(`Expected ${type}, got ${token.type} "${token.value}"`);
    }
    this.advance();
    return token;
  }

  private isAtEnd(): boolean {
    return this.current().type === TokenType.EOF;
  }

  private skipNewlines(): void {
    while (this.current().type === TokenType.Newline) {
      this.advance();
    }
  }

  private skipToNextStatement(): void {
    while (!this.isAtEnd() && this.current().type !== TokenType.Newline) {
      this.advance();
    }
    this.skipNewlines();
  }

  private error(message: string): ParseErrorException {
    const token = this.current();
    return new ParseErrorException(
      message,
      token.line,
      token.column,
      token.offset,
    );
  }
}

class ParseErrorException extends Error {
  line: number;
  column: number;
  offset: number;

  constructor(message: string, line: number, column: number, offset: number) {
    super(message);
    this.line = line;
    this.column = column;
    this.offset = offset;
  }

  toParseError(): ParseError {
    return {
      message: this.message,
      line: this.line,
      column: this.column,
      offset: this.offset,
    };
  }
}
