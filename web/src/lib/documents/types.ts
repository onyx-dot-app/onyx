export type FileEntry = {
  id: string;
  name: string;
  type: 'file' | 'folder';
  children?: FileEntry[];
  url?: string;
  docId?: string;
};

export const defaultSidebarFiles: FileEntry[] = [
  {
    id: 'dhf-file',
    name: 'DHF-008 - MC2-OXO Design History File Checklist_D-signed',
    type: 'file',
    url: 'https://docs.google.com/spreadsheets/d/1ChieZhtyALESO4r-PDxfZsT0jYJHmunuyoYu8Lpo1cs/edit?gid=25002498#gid=25002498',
    docId: '1ChieZhtyALESO4r-PDxfZsT0jYJHmunuyoYu8Lpo1cs',
  },
  {
    id: 'dhf-folder',
    name: 'DHF',
    type: 'folder',
    children: [
      {
        id: "1JaAGEepQr1Gdmc0dLwVM9Q3Grc8-Sb45GSPf6PCBR08",
        name: "3P-M02-32 - MC2 OXO Rev F SGS IEC 60601-1-2 EMC Summary Report_A",
        type: "file",
        url: "https://docs.google.com/document/d/1JaAGEepQr1Gdmc0dLwVM9Q3Grc8-Sb45GSPf6PCBR08/edit?usp=drive_link",
        docId: "1JaAGEepQr1Gdmc0dLwVM9Q3Grc8-Sb45GSPf6PCBR08"
      },
      {
        id: "1Tz-Ux-Ux-Ux-Ux-Ux-Ux-Ux-Ux-Ux-Ux-Ux-Ux-Ux-Ux",
        name: "3P-M02-33 - MC2 OXO Rev F Electrical Safety Test Report",
        type: "file",
        url: "https://docs.google.com/document/d/1Tz-Ux-Ux-Ux-Ux-Ux-Ux-Ux-Ux-Ux-Ux-Ux-Ux-Ux-Ux-Ux/edit?usp=drive_link",
        docId: "1Tz-Ux-Ux-Ux-Ux-Ux-Ux-Ux-Ux-Ux-Ux-Ux-Ux-Ux-Ux"
      },
      {
        id: "nested-folder",
        name: "Technical Documentation",
        type: "folder",
        children: [
          {
            id: "1Ab-Cd-Ef-Gh-Ij-Kl-Mn-Op-Qr-St-Uv-Wx-Yz-12",
            name: "MC2 OXO Technical Specifications",
            type: "file",
            url: "https://docs.google.com/document/d/1Ab-Cd-Ef-Gh-Ij-Kl-Mn-Op-Qr-St-Uv-Wx-Yz-12/edit?usp=drive_link",
            docId: "1Ab-Cd-Ef-Gh-Ij-Kl-Mn-Op-Qr-St-Uv-Wx-Yz-12"
          },
          {
            id: "1Xy-Zw-Vu-Ts-Rq-Po-Nm-Lk-Ji-Hg-Fe-Dc-Ba-34",
            name: "MC2 OXO User Manual",
            type: "file",
            url: "https://docs.google.com/document/d/1Xy-Zw-Vu-Ts-Rq-Po-Nm-Lk-Ji-Hg-Fe-Dc-Ba-34/edit?usp=drive_link",
            docId: "1Xy-Zw-Vu-Ts-Rq-Po-Nm-Lk-Ji-Hg-Fe-Dc-Ba-34"
          }
        ]
      }
    ]
  },
  {
    id: "quality-folder",
    name: "Quality Management",
    type: "folder",
    children: [
      {
        id: "1Qa-Qa-Qa-Qa-Qa-Qa-Qa-Qa-Qa-Qa-Qa-Qa-Qa-Qa-56",
        name: "Quality Management System Manual",
        type: "file",
        url: "https://docs.google.com/document/d/1Qa-Qa-Qa-Qa-Qa-Qa-Qa-Qa-Qa-Qa-Qa-Qa-Qa-Qa-56/edit?usp=drive_link",
        docId: "1Qa-Qa-Qa-Qa-Qa-Qa-Qa-Qa-Qa-Qa-Qa-Qa-Qa-Qa-56"
      },
      {
        id: "1Qb-Qb-Qb-Qb-Qb-Qb-Qb-Qb-Qb-Qb-Qb-Qb-Qb-Qb-78",
        name: "Risk Management Procedures",
        type: "file",
        url: "https://docs.google.com/document/d/1Qb-Qb-Qb-Qb-Qb-Qb-Qb-Qb-Qb-Qb-Qb-Qb-Qb-Qb-78/edit?usp=drive_link",
        docId: "1Qb-Qb-Qb-Qb-Qb-Qb-Qb-Qb-Qb-Qb-Qb-Qb-Qb-Qb-78"
      }
    ]
  }
];
