export interface CustomRefreshTokenResponse {
  access_token: string;
  refresh_token: string;
  session: {
    exp: number;
  };
  userinfo: {
    sub: string;
    familyName: string;
    givenName: string;
    fullName: string;
    userId: string;
    email: string;
  };
}
