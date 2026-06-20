# Forwarding App — Functional Flow

A freight-forwarding / LCS (Logistics Cloud System) Frappe app. **Operations** (the Job)
is the hub: leads/requests flow into it, execution docs (Freight, Custom Clearance,
Transportation, Booking) and invoices are spun out of it, and its `billing_status` is
derived back from those invoices. Everything is gated by an **LCS Subscription** plan.

## End-to-end flow

```mermaid
flowchart TD
    %% ---------- INTAKE ----------
    subgraph INTAKE["1 · Intake"]
        GUEST([Partner / Guest]):::ext
        WWW["www/freight-job-request<br/>public form"]:::ui
        QUOT["Quotation<br/>(ERPNext)"]:::erp
        FJR["Freight Job Request<br/>status = Pending"]:::doc
        GUEST --> WWW -->|submit_job_request| FJR
    end

    %% ---------- JOB HUB ----------
    subgraph HUB["2 · Operations — the Job hub"]
        OPS["Operations (Job)"]:::hub
        COST["Cost Table<br/>(child of Operations)"]:::doc
        OPS -.->|validate → set_billing_status| OPS
        OPS -->|on_update: push awb_number,<br/>cost_center| SYNC[(Freight / Custom Clearance<br/>/ Project)]:::doc
    end

    FJR -->|operator converts| OPS
    QUOT -->|make_operations<br/>Quotation Item → Cost Table| OPS

    %% ---------- EXECUTION ----------
    subgraph EXEC["3 · Execution docs (mapped from Operations)"]
        FRT["Freight<br/>(BL / AWB)"]:::doc
        CC["Custom Clearance"]:::doc
        TRN["Transportation"]:::doc
        BOOK["Container Booking Request"]:::doc
    end
    OPS -->|make_freight| FRT
    OPS -->|make_custom_clearance| CC
    OPS -->|make_transportaion| TRN
    OPS -->|make_booking| BOOK
    FRT -->|validate: sync rows + ref_id<br/>on_update: awb_number| COST

    %% ---------- BILLING ----------
    subgraph BILL["4 · Billing & cost reconciliation"]
        SI["Sales Invoice"]:::erp
        PI["Purchase Invoice"]:::erp
        PE["Payment Entry<br/>(ERPNext)"]:::erp
        SHARE["Public invoice link<br/>/invoice?token=…"]:::ui
    end
    COST -->|make_sales_invoice| SI
    COST -->|make_purchase_invoice| PI
    SI -->|on_update → received_amount| COST
    PI -->|on_update → paid_amount| COST
    SI & PI -->|collect / pay| PE
    SI -->|share_invoice| SHARE
    SI -. docstatus drives .-> OPS

    %% ---------- TRACKING ----------
    subgraph TRACK["5 · Tracking & status"]
        FT["Freight Tracking<br/>(AWB events)"]:::doc
        FJS["Freight Job Status<br/>+ status_history"]:::doc
    end
    OPS --> FJS
    FRT --> FT
    FJS -->|add_status / update_job_status /<br/>master_status_update bulk| FJS

    %% ---------- CROSS-CUTTING ----------
    SUB{{"LCS Subscription<br/>enforce_limit on validate"}}:::gate
    SUB -. blocks new .-> OPS
    SUB -. blocks new .-> SI
    SUB -. blocks new .-> PI
    SUB -. blocks new .-> FT

    subgraph VIEW["6 · Dashboards · Reports · Mobile/SPA API"]
        DASH["Operation & Finance dashboards<br/>get_dashboard_stats / get_finance_stats"]:::ui
        REP["Reports: detailed_report,<br/>P&L, operations_summary…"]:::ui
        MOB["Mobile/SPA: get_job_list, get_job_detail,<br/>form_meta, doc_get/save/submit"]:::ui
    end
    OPS --> DASH
    SI & PI --> REP
    OPS --> MOB

    classDef hub fill:#1d4ed8,color:#fff,stroke:#1e3a8a,stroke-width:2px;
    classDef doc fill:#e0f2fe,color:#075985,stroke:#0284c7;
    classDef erp fill:#fef3c7,color:#92400e,stroke:#d97706;
    classDef ui fill:#dcfce7,color:#166534,stroke:#16a34a;
    classDef gate fill:#fee2e2,color:#991b1b,stroke:#dc2626;
    classDef ext fill:#f3e8ff,color:#6b21a8,stroke:#9333ea;
```

## Reading the flow

| Phase | What happens | Key code |
|-------|--------------|----------|
| **1 Intake** | Partners submit the public job-request form; ERPNext Quotations are mapped into jobs. | `api.submit_job_request`, `custom_methods.make_operations` |
| **2 Job hub** | `Operations` is the spine. `validate` derives `billing_status` from its invoices; `on_update` pushes `awb_number`/`cost_center` onto Freight, Custom Clearance, Project. | `operations.Operations.validate / set_billing_status / on_update` |
| **3 Execution** | Freight, Custom Clearance, Transportation, Container Booking are `get_mapped_doc` spin-offs. Freight syncs its rows back into the Operations **Cost Table** (creating `ref_id` links). | `operations.make_freight/…`, `freight.Freight.validate` |
| **4 Billing** | Cost Table rows become Sales/Purchase Invoice lines. Invoice `on_update` writes `received_amount`/`paid_amount` back to the Cost Table; `on_cancel` reverses. Invoices can be shared via a public token link. | `operations.make_sales_invoice/make_purchase_invoice`, `custom_methods.update_cost_table_in_operations`, `api.share_invoice` |
| **5 Tracking** | `Freight Tracking` holds AWB/BL events; `Freight Job Status` keeps a `status_history` child log, updatable singly or in bulk. | `api.track_awb / update_job_status / master_status_update`, `freight_job_status.add_status` |
| **6 Views** | Dashboards/reports aggregate jobs & invoices; a generic CRUD + form-meta API backs the mobile/SPA front end. | `api.get_dashboard_stats / get_finance_stats / form_meta / doc_save` |
| **Cross-cutting** | Every new `Operations`, `Sales/Purchase Invoice`, `Freight Voucher`, `Freight Tracking` is checked against the active **LCS Subscription** plan limit. Customers/Suppliers get auto `CU-/SU-` codes on insert. | `subscription.enforce_limit`, `naming.set_customer_code/set_supplier_code` |

> The diagram is Mermaid — it renders in the GitHub/VS Code preview and most Markdown viewers.
