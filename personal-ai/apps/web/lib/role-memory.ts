export type RoleMemory = {
  id: string;
  kind: string;
  content: string;
  status: string;
  known_to_character: boolean;
  source_available?: boolean;
  time_label: string;
};
