import { dockerCompose } from "./database";

export default function globalTeardown(): void {
  dockerCompose("down", "--volumes", "--remove-orphans");
}
