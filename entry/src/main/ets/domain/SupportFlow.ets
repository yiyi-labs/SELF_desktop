export class SupportFlow {
  offered: boolean=false;
  accepted: boolean=false;
  offer(): void { this.offered=true;this.accepted=false; }
  accept(): void { if(this.offered)this.accepted=true; }
  close(): void { this.offered=false;this.accepted=false; }
  canWrite(): boolean { return this.accepted; }
}
